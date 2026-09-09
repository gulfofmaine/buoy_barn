import operator
from collections import defaultdict
from functools import reduce

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .erddap_dataset import ErddapDataset
from .erddap_server import ErddapServer
from .platform import Platform
from .timeseries import TimeSeries

SUBJECT_FIELDS = {
    Platform: "platform",
    TimeSeries: "timeseries",
    ErddapDataset: "dataset",
    ErddapServer: "server",
}

_SUBJECT_COLUMNS = tuple(SUBJECT_FIELDS.values())

# An OR of "this column is set and the other three are not", once per column.
_EXACTLY_ONE_SUBJECT = reduce(
    operator.or_,
    (
        Q(**{f"{column}__isnull": column != set_column for column in _SUBJECT_COLUMNS})
        for set_column in _SUBJECT_COLUMNS
    ),
)


def subject_field(subject) -> str:
    """The column `subject` attaches through, or a `ValueError` naming the model that cannot."""
    column = SUBJECT_FIELDS.get(subject._meta.model)
    if column is None:
        raise ValueError(
            f"{subject._meta.label} cannot be a SystemMessage subject; "
            f"expected one of {', '.join(model._meta.label for model in SUBJECT_FIELDS)}",
        )
    return column


class SystemMessageQuerySet(models.QuerySet):
    def outstanding(self):
        """Messages that still need attention.

        Acknowledgement attaches to the (subject, code, constraint_group) row rather than to
        one occurrence, since a recurring problem re-uses the same row. So a message counts
        as outstanding again once it recurs *after* being acknowledged (`acknowledged_at`
        predates `last_seen`) rather than staying silently dismissed forever. Resolved
        messages are never outstanding, regardless of acknowledgement.
        """
        return self.filter(resolved_at__isnull=True).filter(
            Q(acknowledged_at__isnull=True) | Q(acknowledged_at__lt=models.F("last_seen")),
        )

    def for_object(self, obj):
        """Messages attached to a single model instance."""
        return self.filter(**{subject_field(obj): obj.pk})

    def for_objects(self, objs):
        """Messages attached to any of a heterogeneous iterable of model instances.

        `objs` can mix Platforms, TimeSeries, ErddapDatasets and ErddapServers. They are
        grouped by the column they attach through and OR'd together as one
        `Q(<column>__in=[...])` per column, so the whole list resolves in a single query.
        """
        objs = list(objs)
        if not objs:
            return self.none()

        ids_by_column = defaultdict(list)
        for obj in objs:
            ids_by_column[subject_field(obj)].append(obj.pk)

        query = Q()
        for column, object_ids in ids_by_column.items():
            query |= Q(**{f"{column}__in": object_ids})

        return self.filter(query)


class SystemMessageManager(models.Manager.from_queryset(SystemMessageQuerySet)):
    pass


class SystemMessage(models.Model):
    """A problem or notable event tied to some other model instance.

    Raised by the refresh/error-handling path and surfaced in the admin, so operators see
    "this platform's ERDDAP dataset has been returning 404s" instead of having to read logs.

    Attached to its subject through one nullable foreign key per subject model rather than a
    generic relation: the set of subject models does not grow, and real columns are what let
    the admin's reach lookups use an index.
    """

    platform = models.ForeignKey(
        Platform,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="system_messages",
    )
    timeseries = models.ForeignKey(
        TimeSeries,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="system_messages",
    )
    dataset = models.ForeignKey(
        ErddapDataset,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="system_messages",
    )
    server = models.ForeignKey(
        ErddapServer,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="system_messages",
    )

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
        CONSTRAINT_OUT_OF_RANGE = "constraint_out_of_range"
        NO_MATCHING_TIME = "no_matching_time"
        TIME_RANGE_REPORTED = "time_range_reported"
        TASK_SOFT_TIME_LIMIT = "task_soft_time_limit"

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
            models.CheckConstraint(
                condition=_EXACTLY_ONE_SUBJECT,
                name="system_message_exactly_one_subject",
            ),
            # One partial unique index per subject column rather than one combined
            # constraint: Postgres treats NULLs as distinct, so a single unique constraint
            # over all four columns (three of which are always NULL) would never fire,
            # and every recurrence would insert a new row instead of bumping `occurrences`.
            *[
                models.UniqueConstraint(
                    fields=[column, "code", "constraint_group"],
                    condition=Q(**{f"{column}__isnull": False}),
                    name=f"unique_{column}_system_message",
                )
                for column in _SUBJECT_COLUMNS
            ],
        ]

    def __str__(self):
        return f"{self.get_level_display()} - {self.code} - {self.subject}"

    @property
    def subject_model(self):
        """The model of whichever subject foreign key is set."""
        for model, column in SUBJECT_FIELDS.items():
            if getattr(self, f"{column}_id") is not None:
                return model
        return None

    @property
    def subject_id(self):
        """The pk of whichever subject foreign key is set, without loading the row."""
        model = self.subject_model
        if model is None:
            return None
        return getattr(self, f"{SUBJECT_FIELDS[model]}_id")

    @property
    def subject(self):
        """Whichever subject foreign key is set, without touching the other three."""
        model = self.subject_model
        if model is None:
            return None
        return getattr(self, SUBJECT_FIELDS[model])
