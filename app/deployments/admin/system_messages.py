"""The SystemMessage feature: reach/containment, sidebar gathering, the badge, and the admin.

Acknowledging a SystemMessage is global: it dismisses the message for everyone, everywhere.
So a page may only offer an inline Acknowledge button for a message whose blast radius is
entirely contained by that page -- otherwise a click on one platform's page silently
dismisses a problem that four other platforms still have. The containment gate below is the
whole point of this module, and it is deliberately computed in one place so the gate and
the impact list on the SystemMessage change page (the page the gate sends you to when it
refuses) cannot drift apart and disagree about what a message reaches.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from django.contrib.admin import SimpleListFilter
from django.contrib.admin.utils import unquote
from django.contrib.admin.views.main import ChangeList
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis import admin
from django.core.exceptions import PermissionDenied
from django.db.models.query import QuerySet
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.http.request import HttpRequest
from django.shortcuts import get_object_or_404
from django.urls import NoReverseMatch, path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.http import url_has_allowed_host_and_scheme

from buoy_barn.observability.promql import explore_url, query_for

from ..models import ErddapDataset, ErddapServer, Platform, SystemMessage, TimeSeries

#: The axis containment is measured along, per page model. On a Platform page a message is
#: contained when every platform it reaches is this platform; on a Dataset page, when every
#: dataset it reaches is this dataset; and so on. Same rule, different unit.
_REACH_AXES = {
    Platform: "platform_ids",
    ErddapDataset: "dataset_ids",
    ErddapServer: "server_ids",
    TimeSeries: "timeseries_ids",
}

#: How a message subject of each type is found in the TimeSeries table. Every kind of subject
#: resolves through TimeSeries because that is the only model that joins platforms, datasets
#: and servers together -- which is what makes the whole reach computation four queries at
#: worst, one per subject type present, regardless of how many messages there are.
_SUBJECT_COLUMN = {
    Platform: "platform_id",
    ErddapDataset: "dataset_id",
    ErddapServer: "dataset__server_id",
    TimeSeries: "id",
}

#: The columns `_reach_rows` selects, and the position of each. Every key in
#: `_SUBJECT_COLUMN` is one of these, so a single four-column row serves as both the lookup
#: key and the reach payload.
_REACH_COLUMNS = ("id", "platform_id", "dataset_id", "dataset__server_id")

#: Short, human names for subject types. `verbose_name` gives "erddap dataset"; on a sidebar
#: row that has to lead with what the message is about, "Dataset" reads better.
_SUBJECT_LABELS = {
    Platform: "Platform",
    ErddapDataset: "Dataset",
    ErddapServer: "Server",
    TimeSeries: "Timeseries",
}

#: Plural nouns for the spill count ("affects 3 platforms").
_REACH_NOUNS = {
    Platform: "platforms",
    ErddapDataset: "datasets",
    ErddapServer: "servers",
    TimeSeries: "timeseries",
}

_LEVEL_COLORS = {
    SystemMessage.Level.DANGER: "red",
    SystemMessage.Level.WARNING: "orange",
    SystemMessage.Level.INFO: "gray",
}

#: Most alarming first, so a split badge leads with the worst thing it has to report.
_LEVEL_ORDER = [
    SystemMessage.Level.DANGER,
    SystemMessage.Level.WARNING,
    SystemMessage.Level.INFO,
]


@dataclass(frozen=True)
class MessageReach:
    """Everything one message touches, in each of the four units containment is measured in."""

    platform_ids: frozenset
    dataset_ids: frozenset
    server_ids: frozenset
    timeseries_ids: frozenset

    def ids_along(self, model) -> frozenset:
        """The reach along the axis `model` pages measure containment in."""
        axis = _REACH_AXES.get(model)
        if axis is None:
            return frozenset()
        return getattr(self, axis)


_EMPTY_REACH = MessageReach(frozenset(), frozenset(), frozenset(), frozenset())


def _reach_rows(column, ids):
    """One query resolving a whole group of same-typed subjects to what they touch."""
    return TimeSeries.objects.filter(**{f"{column}__in": list(ids)}).values_list(*_REACH_COLUMNS)


def compute_message_reach(messages) -> dict[int, MessageReach]:
    """Map each message's pk to what it reaches, in a constant number of queries.

    The naive version of this -- ask each message's subject what it touches -- costs a query
    per message, which is exactly the shape a sidebar of ten messages must not have. Instead
    the messages are grouped by subject type and each group resolved with a single
    `TimeSeries` query, so the cost is at most four queries (one per subject type that is
    actually present) whether there is one message or a hundred.

    A subject always appears in its own axis even when nothing joins to it: a dataset with no
    timeseries still reaches itself, and must stay dismissable on its own page.
    """
    messages = list(messages)
    if not messages:
        return {}

    model_by_content_type = {
        ContentType.objects.get_for_model(model).id: model for model in _SUBJECT_COLUMN
    }

    ids_by_model = defaultdict(set)
    for message in messages:
        model = model_by_content_type.get(message.content_type_id)
        if model is not None:
            ids_by_model[model].add(message.object_id)

    accumulated: dict[tuple[Any, int], dict[str, set]] = {}
    for model, ids in ids_by_model.items():
        for subject_id in ids:
            seeded = {axis: set() for axis in _REACH_AXES.values()}
            seeded[_REACH_AXES[model]].add(subject_id)
            accumulated[(model, subject_id)] = seeded

        column = _SUBJECT_COLUMN[model]
        key_index = _REACH_COLUMNS.index(column)
        for row in _reach_rows(column, ids):
            reached = accumulated[(model, row[key_index])]
            reached["timeseries_ids"].add(row[0])
            reached["platform_ids"].add(row[1])
            reached["dataset_ids"].add(row[2])
            reached["server_ids"].add(row[3])

    reach_by_message = {}
    for message in messages:
        model = model_by_content_type.get(message.content_type_id)
        reached = accumulated.get((model, message.object_id))
        if reached is None:
            reach_by_message[message.pk] = _EMPTY_REACH
            continue
        reach_by_message[message.pk] = MessageReach(
            platform_ids=frozenset(reached["platform_ids"]),
            dataset_ids=frozenset(reached["dataset_ids"]),
            server_ids=frozenset(reached["server_ids"]),
            timeseries_ids=frozenset(reached["timeseries_ids"]),
        )

    return reach_by_message


def _prefetched_or_related(manager, *related):
    """The manager's rows, using an existing prefetch when the caller already loaded them.

    `related_subjects` is called both from a change view (one object, nothing prefetched --
    wants `select_related`) and from a changelist (many objects, all prefetched -- where a
    `select_related` call would throw the prefetch away and reintroduce the N+1 it exists to
    prevent). Checking for a populated result cache lets one function serve both.
    """
    queryset = manager.all()
    if queryset._result_cache is None:  # noqa: SLF001 - no public "is this prefetched?" API
        queryset = queryset.select_related(*related)
    return queryset


def related_subjects(obj) -> list:
    """The objects whose messages belong on `obj`'s change page.

    A problem is rarely recorded against the thing an operator is looking at: a platform's
    data stops arriving because a *server* is refusing requests, and the message is attached
    to the server. So each page gathers up and down its own chain -- a platform reaches
    through its timeseries to their datasets and those datasets' servers -- rather than
    showing only messages whose subject is literally this row.
    """
    if isinstance(obj, Platform):
        subjects = [obj]
        for timeseries in _prefetched_or_related(obj.timeseries_set, "dataset", "dataset__server"):
            subjects.extend([timeseries, timeseries.dataset, timeseries.dataset.server])
    elif isinstance(obj, ErddapDataset):
        subjects = [obj, obj.server, *_prefetched_or_related(obj.timeseries_set)]
    elif isinstance(obj, ErddapServer):
        subjects = [obj, *_prefetched_or_related(obj.erddapdataset_set)]
    elif isinstance(obj, TimeSeries):
        subjects = [obj, obj.dataset, obj.dataset.server]
    else:
        subjects = [obj]

    deduped = {}
    for subject in subjects:
        if subject is not None:
            deduped.setdefault((subject._meta.model, subject.pk), subject)
    return list(deduped.values())


def _subject_key(obj) -> tuple[int, int]:
    return (ContentType.objects.get_for_model(obj).id, obj.pk)


def _gather_messages(subjects):
    """Every outstanding message on any of `subjects`, in one query."""
    return list(
        SystemMessage.objects.outstanding()
        .for_objects(subjects)
        .select_related("content_type", "acknowledged_by"),
    )


def _admin_url(admin_site, obj) -> str:
    if obj is None or obj.pk is None:
        return ""
    meta = obj._meta
    try:
        return reverse(
            f"{admin_site.name}:{meta.app_label}_{meta.model_name}_change",
            args=[obj.pk],
        )
    except NoReverseMatch:
        return ""


def _subject_label(obj, message) -> str:
    if obj is None:
        return str(message.content_type)
    model = obj._meta.model
    label = _SUBJECT_LABELS.get(model, model._meta.verbose_name.title())
    return f"{label} · {obj}"


def _promql_context(message, subject) -> dict:
    """The context `promql.query_for` wants, filled in from the message's subject.

    `constraint_group` is a model field rather than a context key, and the fetch-failure
    handlers record neither the dataset nor the server name (they have no need to -- the
    subject already says which one it is). Both have to be supplied here or every outcome-code
    message would render without a query.
    """
    context = {**(message.context or {}), "constraint_group": message.constraint_group}

    if not context.get("dataset"):
        if isinstance(subject, ErddapDataset):
            context["dataset"] = subject.name
        elif isinstance(subject, TimeSeries):
            context["dataset"] = subject.dataset.name

    if not context.get("server"):
        if isinstance(subject, ErddapServer):
            context["server"] = subject.name
        elif isinstance(subject, ErddapDataset):
            context["server"] = subject.server.name
        elif isinstance(subject, TimeSeries):
            context["server"] = subject.dataset.server.name

    return context


@dataclass(frozen=True)
class SystemMessageRow:
    """One rendered sidebar entry. All the logic is decided here, none of it in the template."""

    message: SystemMessage
    subject_label: str
    subject_url: str
    message_url: str
    acknowledge_url: str
    can_acknowledge: bool
    spill_count: int
    reach_count: int
    reach_label: str
    level_color: str
    promql: str | None
    grafana_url: str | None


def build_system_message_rows(obj, admin_site, subjects=None) -> list[SystemMessageRow]:
    """The sidebar for `obj`'s change page: gather, judge containment, and pre-render."""
    subjects = related_subjects(obj) if subjects is None else subjects
    subject_by_key = {_subject_key(subject): subject for subject in subjects}

    messages = _gather_messages(subjects)
    reach_by_message = compute_message_reach(messages)

    page_model = obj._meta.model
    reach_label = _REACH_NOUNS.get(page_model, "objects")

    rows = []
    for message in messages:
        subject = subject_by_key.get((message.content_type_id, message.object_id))
        reach = reach_by_message.get(message.pk, _EMPTY_REACH)
        axis = reach.ids_along(page_model)
        spilled = axis - {obj.pk}

        promql = query_for(message.code, _promql_context(message, subject))

        rows.append(
            SystemMessageRow(
                message=message,
                subject_label=_subject_label(subject, message),
                subject_url=_admin_url(admin_site, subject),
                message_url=_admin_url(admin_site, message),
                acknowledge_url=reverse(
                    f"{admin_site.name}:deployments_systemmessage_acknowledge",
                    args=[message.pk],
                ),
                can_acknowledge=not spilled,
                spill_count=len(spilled),
                reach_count=len(axis),
                reach_label=reach_label,
                level_color=_LEVEL_COLORS.get(message.level, "gray"),
                promql=promql,
                grafana_url=explore_url(promql) if promql else None,
            ),
        )

    return rows


@dataclass(frozen=True)
class SystemMessageBadge:
    """The split badge's two halves: what this row owns, and what it merely shares."""

    contained: list
    spilling: list


def annotate_system_message_badges(objs, page_model) -> list:
    """Attach a `SystemMessageBadge` to every object on a changelist page, in bulk.

    Computed once for the whole page rather than once per row: the changelist calls the
    display function once per object, so anything that queries in there is an N+1 by
    construction. `SystemMessageChangeList` calls this from `get_results`, where the page's
    objects are all in hand at once.
    """
    objs = list(objs)
    if not objs:
        return objs

    subjects_by_pk = {obj.pk: related_subjects(obj) for obj in objs}

    deduped_subjects = {}
    for subjects in subjects_by_pk.values():
        for subject in subjects:
            deduped_subjects.setdefault(_subject_key(subject), subject)

    messages = _gather_messages(deduped_subjects.values())
    reach_by_message = compute_message_reach(messages)

    messages_by_subject = defaultdict(list)
    for message in messages:
        messages_by_subject[(message.content_type_id, message.object_id)].append(message)

    for obj in objs:
        contained = defaultdict(int)
        spilling = defaultdict(int)
        seen = set()

        for subject in subjects_by_pk[obj.pk]:
            for message in messages_by_subject.get(_subject_key(subject), ()):
                if message.pk in seen:
                    continue
                seen.add(message.pk)

                reach = reach_by_message.get(message.pk, _EMPTY_REACH)
                if reach.ids_along(page_model) - {obj.pk}:
                    subject_model = subject._meta.model
                    spilling[_SUBJECT_LABELS.get(subject_model, "other").lower()] += 1
                else:
                    contained[message.level] += 1

        obj._system_message_badge = SystemMessageBadge(  # noqa: SLF001 - carrier for the display fn
            contained=[(level, contained[level]) for level in _LEVEL_ORDER if contained.get(level)],
            spilling=sorted(spilling.items()),
        )

    return objs


@admin.display(description="System messages")
def system_message_status(obj: ErddapDataset | Platform | TimeSeries):
    """Split badge: what this row can act on, then muted, what it only shares.

    The two halves are not interchangeable. "2 danger" is a problem this row owns and can
    dismiss from its own page; "(+1 server)" is a problem it merely suffers, shared with
    platforms nobody looking at this changelist can see. Running them together would invite
    exactly the global dismissal the containment rule exists to prevent.
    """
    badge = getattr(obj, "_system_message_badge", None)
    if badge is None:
        badge = annotate_system_message_badges([obj], obj._meta.model)[0]._system_message_badge  # noqa: SLF001

    if not badge.contained and not badge.spilling:
        return format_html("<span style='color: gray;'>{}</span>", "None")

    contained_html = format_html_join(
        " ",
        "<span style='color: {};'>{} {}</span>",
        (
            (_LEVEL_COLORS.get(level, "gray"), count, SystemMessage.Level(level).label.lower())
            for level, count in badge.contained
        ),
    )

    if not badge.spilling:
        return contained_html

    spilling_html = format_html_join(
        ", ",
        "+{} {}",
        ((count, label) for label, count in badge.spilling),
    )
    return format_html(
        "{} <span style='color: gray;' title='{}'>({})</span>",
        contained_html,
        "Also affects other rows, so it can only be acknowledged from its own page",
        spilling_html,
    )


class SystemMessageChangeList(ChangeList):
    """A changelist that pre-computes the system message badge for its whole page."""

    def get_results(self, request):
        super().get_results(request)
        if system_message_status in self.model_admin.list_display:
            self.result_list = annotate_system_message_badges(self.result_list, self.model)


class SystemMessageSidebarMixin:
    """Puts outstanding messages for a page's whole chain into Django's own right sidebar."""

    change_form_template = "admin/deployments/change_form.html"

    def related_subjects(self, obj) -> list:
        """The objects this page gathers messages from. Overridden per admin where it differs."""
        return related_subjects(obj)

    def get_changelist(self, request, **kwargs):
        return SystemMessageChangeList

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = {**(extra_context or {})}
        obj = self.get_object(request, unquote(object_id))
        if obj is not None:
            extra_context["system_messages"] = build_system_message_rows(
                obj,
                self.admin_site,
                subjects=self.related_subjects(obj),
            )
        return super().change_view(request, object_id, form_url, extra_context)


class SystemMessageStateFilter(SimpleListFilter):
    """Outstanding / acknowledged / resolved, defaulting to outstanding.

    A system message list that opens on *everything ever recorded* is a list nobody reads, so
    the unfiltered view is not the default. The stock "All" choice is replaced by an explicit
    lookup of the same name, because Django treats "no parameter" as "All" and there is no
    other way to make "no parameter" mean something else while still offering a way out.
    """

    title = "state"
    parameter_name = "state"
    default_value = "outstanding"

    def lookups(self, request: Any, model_admin: Any) -> list[tuple[Any, str]]:
        return [
            ("outstanding", "Outstanding"),
            ("acknowledged", "Acknowledged"),
            ("resolved", "Resolved"),
            ("all", "All"),
        ]

    def choices(self, changelist):
        """Replace the implicit "All" with our own lookups, one of which is selected by default."""
        selected = self.value() or self.default_value
        for lookup, title in self.lookup_choices:
            yield {
                "selected": selected == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }

    def queryset(self, request: Any, queryset: QuerySet[Any]) -> QuerySet[Any] | None:
        value = self.value() or self.default_value
        if value == "outstanding":
            return queryset.outstanding()
        if value == "acknowledged":
            return queryset.filter(acknowledged_at__isnull=False, resolved_at__isnull=True)
        if value == "resolved":
            return queryset.filter(resolved_at__isnull=False)
        return queryset


@admin.register(SystemMessage)
class SystemMessageAdmin(admin.ModelAdmin):
    """Read-only-except-acknowledgement admin for machine-written messages.

    Every field here is written by the refresh pipeline. A human editing one by hand is not a
    correction, it is a lie about what the system observed -- so the only thing this admin
    lets anyone change is whether the message has been acknowledged, and even that goes
    through actions and the sidebar button rather than free-form editing.
    """

    list_display = [
        "subject_link",
        "level",
        "code",
        "short_message",
        "occurrences",
        "last_seen",
        "state",
    ]
    list_filter = [SystemMessageStateFilter, "level", "code", "content_type"]
    search_fields = ["message", "code"]
    date_hierarchy = "last_seen"

    actions = ["acknowledge_messages", "unacknowledge_messages"]

    fields = [
        "subject_link",
        "level",
        "code",
        "constraint_group",
        "message",
        "context",
        "first_seen",
        "last_seen",
        "occurrences",
        "acknowledged_at",
        "acknowledged_by",
        "resolved_at",
        "promql_query",
        "impact",
    ]

    #: The only two fields a human is allowed to write.
    editable_fields = ("acknowledged_at", "acknowledged_by")

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        queryset = super().get_queryset(request)
        return queryset.select_related("content_type", "acknowledged_by").prefetch_related(
            "subject",
        )

    def get_readonly_fields(self, request, obj=None):
        return [name for name in self.fields if name not in self.editable_fields]

    def has_add_permission(self, request):
        """Messages are recorded by the refresh pipeline, never typed in."""
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:message_id>/acknowledge/",
                self.admin_site.admin_view(self.acknowledge_view),
                name="deployments_systemmessage_acknowledge",
            ),
        ]
        return custom + urls

    def acknowledge_view(self, request, message_id):
        """Acknowledge one message and bounce back to the page the button was clicked on.

        POST only, because acknowledging is a state change and a GET-able one would be
        acknowledged by every link prefetcher and crawler that touched the page. The `next`
        parameter is validated rather than trusted: it arrives in a form body on a page that
        renders operator-visible content, and an unchecked redirect target here would be a
        plain open redirect out of an authenticated admin session.
        """
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        if not self.has_change_permission(request):
            raise PermissionDenied

        message = get_object_or_404(SystemMessage, pk=message_id)
        message.acknowledged_at = timezone.now()
        message.acknowledged_by = request.user
        message.save(update_fields=["acknowledged_at", "acknowledged_by"])

        self.message_user(request, f"Acknowledged '{message}'.")

        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return HttpResponseRedirect(next_url)

        return HttpResponseRedirect(
            reverse(
                f"{self.admin_site.name}:deployments_systemmessage_change",
                args=[message.pk],
            ),
        )

    @admin.display(description="Subject")
    def subject_link(self, obj: SystemMessage):
        subject = obj.subject
        label = _subject_label(subject, obj)
        url = _admin_url(self.admin_site, subject)
        if not url:
            return label
        return format_html("<a href='{}'>{}</a>", url, label)

    @admin.display(description="Message")
    def short_message(self, obj: SystemMessage):
        limit = 90
        if len(obj.message) <= limit:
            return obj.message
        return f"{obj.message[:limit]}…"

    @admin.display(description="State")
    def state(self, obj: SystemMessage):
        if obj.resolved_at is not None:
            return format_html("<span style='color: gray;' title='{}'>Resolved</span>", obj.resolved_at)
        if obj.acknowledged_at is not None and obj.acknowledged_at >= obj.last_seen:
            return format_html(
                "<span style='color: gray;' title='{}'>Acknowledged</span>",
                f"{obj.acknowledged_at} by {obj.acknowledged_by or 'unknown'}",
            )
        return format_html(
            "<span style='color: {};'>Outstanding</span>",
            _LEVEL_COLORS.get(obj.level, "gray"),
        )

    @admin.display(description="PromQL")
    def promql_query(self, obj: SystemMessage):
        query = query_for(obj.code, _promql_context(obj, obj.subject))
        if not query:
            return "No metric is associated with this code."

        url = explore_url(query)
        if not url:
            return format_html("<pre>{}</pre>", query)
        return format_html(
            "<pre>{}</pre><a href='{}' rel='noreferrer'>Open in Grafana</a>",
            query,
            url,
        )

    @admin.display(description="Impact")
    def impact(self, obj: SystemMessage):
        """Everything acknowledging this message would dismiss it for.

        Deliberately built from the same `compute_message_reach` the sidebar's containment
        gate uses. If this page and the gate computed reach separately they would eventually
        disagree, and the disagreement would show up as a button that dismisses more than the
        page it sits on admits to.
        """
        reach = compute_message_reach([obj]).get(obj.pk, _EMPTY_REACH)

        sections = [
            ("Platforms", Platform.objects.filter(pk__in=reach.platform_ids).order_by("name")),
            (
                "Datasets",
                ErddapDataset.objects.filter(pk__in=reach.dataset_ids)
                .select_related("server")
                .order_by("name"),
            ),
            (
                "Timeseries",
                TimeSeries.objects.filter(pk__in=reach.timeseries_ids).select_related(
                    "platform",
                    "data_type",
                ),
            ),
        ]

        rendered = []
        for title, queryset in sections:
            items = list(queryset)
            if not items:
                continue
            links = format_html_join(
                "",
                "<li><a href='{}'>{}</a></li>",
                ((_admin_url(self.admin_site, item), str(item)) for item in items),
            )
            rendered.append(
                format_html("<p><strong>{} ({})</strong></p><ul>{}</ul>", title, len(items), links),
            )

        if not rendered:
            return "This message does not reach any platforms, datasets or timeseries."

        return format_html_join("", "{}", ((part,) for part in rendered))

    @admin.action(description="Acknowledge selected system messages")
    def acknowledge_messages(self, request, queryset):
        count = queryset.update(acknowledged_at=timezone.now(), acknowledged_by=request.user)
        self.message_user(request, f"Acknowledged {count} system messages.")

    @admin.action(description="Un-acknowledge selected system messages")
    def unacknowledge_messages(self, request, queryset):
        count = queryset.update(acknowledged_at=None, acknowledged_by=None)
        self.message_user(request, f"Un-acknowledged {count} system messages.")
