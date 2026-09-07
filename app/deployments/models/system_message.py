from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from django.utils import timezone


class SystemMessageQuerySet(models.QuerySet):
    def outstanding(self):
        """Messages that still need attention.

        Acknowledgement is global to the (subject, code, constraint_group) row, not to a
        single occurrence: there is nothing else to attach an acknowledgement to, since a
        recurring problem re-uses the same row instead of creating a new one (see the
        unique constraint below). So a message counts as outstanding again once it recurs
        *after* it was acknowledged -- `acknowledged_at` predates `last_seen` -- rather than
        staying silently dismissed forever. Resolved messages are never outstanding,
        regardless of acknowledgement.
        """
        return self.filter(resolved_at__isnull=True).filter(
            Q(acknowledged_at__isnull=True) | Q(acknowledged_at__lt=models.F("last_seen")),
        )

    def for_object(self, obj):
        """Messages attached to a single model instance."""
        content_type = ContentType.objects.get_for_model(obj)
        return self.filter(content_type=content_type, object_id=obj.pk)

    def for_objects(self, objs):
        """Messages attached to any of a heterogeneous iterable of model instances.

        `objs` can mix Platforms, TimeSeries, ErddapDatasets, etc. Filtering naively (one
        query per object, or per type) is what a dashboard listing "all outstanding
        messages for these datasets" would do by default, and that does not scale. Instead
        group the objects by their ContentType and OR together one
        `Q(content_type=..., object_id__in=[...])` per type, so the whole heterogeneous
        list resolves in a single query.
        """
        objs = list(objs)
        if not objs:
            return self.none()

        ids_by_type = {}
        for obj in objs:
            content_type = ContentType.objects.get_for_model(obj)
            ids_by_type.setdefault(content_type, []).append(obj.pk)

        query = Q()
        for content_type, object_ids in ids_by_type.items():
            query |= Q(content_type=content_type, object_id__in=object_ids)

        return self.filter(query)


class SystemMessageManager(models.Manager.from_queryset(SystemMessageQuerySet)):
    pass


class SystemMessage(models.Model):
    """A problem or notable event tied to some other model instance.

    Raised by the refresh/error-handling path (and eventually surfaced in the admin) so
    operators see "this platform's ERDDAP dataset has been returning 404s" instead of having
    to read logs. Attached to its subject via a generic foreign key rather than a set of
    nullable FKs, one per subject model, because the set of things that can misbehave --
    platforms, datasets, servers, individual timeseries -- keeps growing and none of those
    models should have to know about system messages.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    subject = GenericForeignKey("content_type", "object_id")

    class Level(models.TextChoices):
        INFO = "info"
        WARNING = "warning"
        DANGER = "danger"

    class Code(models.TextChoices):
        END_TIME_RETIRED = "end_time_retired"
        END_TIME_CLEARED = "end_time_cleared"
        BACKOFF_INCREASED = "backoff_increased"
        NOT_FOUND = "not_found"
        FORBIDDEN = "forbidden"
        UNRECOGNIZED_VARIABLE = "unrecognized_variable"
        UNRECOGNIZED_CONSTRAINT = "unrecognized_constraint"
        SERVER_ERROR = "server_error"
        UNKNOWN_ERROR = "unknown_error"

    code = models.CharField(choices=Code, max_length=64)
    constraint_group = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text=(
            "The `metrics.constraint_group_id()` hash of the constraints this message concerns, "
            "or blank for a subject with no constraint group. Distinguishes messages for the "
            "same subject and code raised against different constraint groups, so two depths on "
            "the same dataset each get their own row instead of clobbering one another -- and so "
            "a message joins to the buoybarn.erddap.constraint_group.info metric."
        ),
    )
    level = models.CharField(choices=Level, max_length=16)
    message = models.TextField()
    context = models.JSONField(default=dict, blank=True)

    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    occurrences = models.PositiveIntegerField(default=1)

    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    objects = SystemMessageManager()

    class Meta:
        ordering = ["-last_seen"]
        constraints = [
            # Also the index the generic-relation lookups use: `for_object` and `for_objects`
            # filter on (content_type, object_id), which this covers as a leading prefix, so a
            # separate index on those two would be redundant writes on a hot path.
            models.UniqueConstraint(
                fields=["content_type", "object_id", "code", "constraint_group"],
                name="unique_system_message",
            ),
        ]

    def __str__(self):
        return f"{self.get_level_display()} - {self.code} - {self.subject}"
