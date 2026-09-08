"""The SystemMessage feature: reach/containment, sidebar gathering, the badge, and the admin.

Acknowledging a SystemMessage is global.
A page may only offer an inline Acknowledge button for a message whose blast radius is
entirely contained by that page.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from django.contrib.admin import SimpleListFilter
from django.contrib.admin.utils import unquote
from django.contrib.admin.views.main import ChangeList
from django.contrib.gis import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce, Greatest
from django.db.models.query import QuerySet
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.http.request import HttpRequest
from django.shortcuts import get_object_or_404
from django.urls import NoReverseMatch, path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.http import url_has_allowed_host_and_scheme

from buoy_barn.observability import metrics
from buoy_barn.observability.promql import explore_url, query_for

from ..models import ErddapDataset, ErddapServer, Platform, SystemMessage, TimeSeries
from ..models.system_message import SUBJECT_FIELDS


@dataclass(frozen=True)
class SubjectKind:
    """Everything the admin needs to know about one kind of message subject.

    Every subject resolves through `TimeSeries` because that is the only model joining
    platforms, datasets and servers.
    """

    field: str  # the SystemMessage FK column
    reach_attr: str  # the MessageReach attribute containment is measured on
    timeseries_column: str  # how this subject is found in the TimeSeries table
    label: str  # short display name, e.g. "Dataset"
    plural: str  # plural noun for the spill count, e.g. "datasets"
    paths: tuple[str, ...]  # lookups from SystemMessage back to rows of this model


SUBJECT_KINDS: dict[type, SubjectKind] = {
    Platform: SubjectKind(
        field=SUBJECT_FIELDS[Platform],
        reach_attr="platform_ids",
        timeseries_column="platform_id",
        label="Platform",
        plural="platforms",
        paths=(
            "platform",
            "timeseries__platform",
            "dataset__timeseries__platform",
            "server__erddapdataset__timeseries__platform",
        ),
    ),
    TimeSeries: SubjectKind(
        field=SUBJECT_FIELDS[TimeSeries],
        reach_attr="timeseries_ids",
        timeseries_column="id",
        label="Timeseries",
        plural="timeseries",
        paths=(
            "timeseries",
            "dataset__timeseries",
            "server__erddapdataset__timeseries",
        ),
    ),
    ErddapDataset: SubjectKind(
        field=SUBJECT_FIELDS[ErddapDataset],
        reach_attr="dataset_ids",
        timeseries_column="dataset_id",
        label="Dataset",
        plural="datasets",
        paths=(
            "dataset",
            "server__erddapdataset",
            "timeseries__dataset",
        ),
    ),
    ErddapServer: SubjectKind(
        field=SUBJECT_FIELDS[ErddapServer],
        reach_attr="server_ids",
        timeseries_column="dataset__server_id",
        label="Server",
        plural="servers",
        paths=(
            "server",
            "dataset__server",
            "timeseries__dataset__server",
        ),
    ),
}

# The columns `_reach_rows` selects. "id" is TimeSeries's own column too, so de-duplicate it.
_REACH_COLUMNS = tuple(
    dict.fromkeys(("id", *(kind.timeseries_column for kind in SUBJECT_KINDS.values()))),
)

# Where each reach attribute lands in a `_reach_rows` row, so `compute_message_reach` can read
# a row by name instead of by position.
_REACH_COLUMN_ATTRS = tuple(
    (_REACH_COLUMNS.index(kind.timeseries_column), kind.reach_attr) for kind in SUBJECT_KINDS.values()
)

_LEVEL_COLORS = {
    SystemMessage.Level.DANGER: "red",
    SystemMessage.Level.WARNING: "orange",
    SystemMessage.Level.INFO: "gray",
}

# Most alarming first, so a split badge leads with the worst thing it has to report.
_LEVEL_ORDER = [
    SystemMessage.Level.DANGER,
    SystemMessage.Level.WARNING,
    SystemMessage.Level.INFO,
]

# Enough of each subject chain to render a sidebar row's label and PromQL query without a
# query per row.
_SUBJECT_SELECT_RELATED = (
    "platform",
    "timeseries__platform",
    "timeseries__data_type",
    "timeseries__dataset__server",
    "dataset__server",
    "server",
)


@dataclass(frozen=True)
class MessageReach:
    """Everything one message touches, in each of the four units containment is measured in."""

    platform_ids: frozenset
    dataset_ids: frozenset
    server_ids: frozenset
    timeseries_ids: frozenset

    def ids_along(self, model) -> frozenset:
        """The reach along the axis `model` pages measure containment in."""
        kind = SUBJECT_KINDS.get(model)
        if kind is None:
            return frozenset()
        return getattr(self, kind.reach_attr)


_EMPTY_REACH = MessageReach(frozenset(), frozenset(), frozenset(), frozenset())


def _reach_rows(column, ids):
    """One query resolving a whole group of same-typed subjects to what they touch."""
    return TimeSeries.objects.filter(**{f"{column}__in": list(ids)}).values_list(*_REACH_COLUMNS)


def compute_message_reach(messages) -> dict[int, MessageReach]:
    """Map each message's pk to what it reaches, in a constant number of queries.

    The naive version of this (ask each message's subject what it touches) costs a query
    per message, which is the shape a sidebar of ten messages must not have. Instead
    the messages are grouped by which subject foreign key they set and each group resolved
    with a single `TimeSeries` query, so the cost is at most four queries (one per subject
    type that is actually present) whether there is one message or a hundred.

    A subject always appears in its own axis even when nothing joins to it: a dataset with no
    timeseries still reaches itself, and must stay dismissable on its own page.
    """
    messages = list(messages)
    if not messages:
        return {}

    ids_by_model = defaultdict(set)
    for message in messages:
        if message.subject_model is not None:
            ids_by_model[message.subject_model].add(message.subject_id)

    accumulated: dict[tuple[Any, int], dict[str, set]] = {}
    for model, ids in ids_by_model.items():
        kind = SUBJECT_KINDS[model]
        for subject_id in ids:
            seeded = {other.reach_attr: set() for other in SUBJECT_KINDS.values()}
            seeded[kind.reach_attr].add(subject_id)
            accumulated[(model, subject_id)] = seeded

        key_index = _REACH_COLUMNS.index(kind.timeseries_column)
        for row in _reach_rows(kind.timeseries_column, ids):
            reached = accumulated[(model, row[key_index])]
            for index, reach_attr in _REACH_COLUMN_ATTRS:
                reached[reach_attr].add(row[index])

    reach_by_message = {}
    for message in messages:
        reached = accumulated.get((message.subject_model, message.subject_id))
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


def _paths_for(page_model) -> tuple[str, ...]:
    """The lookups from `SystemMessage` back to rows of `page_model`, or `()` if none apply."""
    kind = SUBJECT_KINDS.get(page_model)
    return kind.paths if kind else ()


def messages_reaching(page_model, pks) -> dict[int, set[int]]:
    """The pks of the outstanding messages reaching each of `pks`, one query per path.

    Queried per path rather than through one OR'd filter because an OR over four
    multi-valued paths returns each message once per matching join row, so the caller would
    have to de-duplicate rows the database had already multiplied.
    """
    pks = list(pks)
    reaching: dict[int, set[int]] = defaultdict(set)
    for message_path in _paths_for(page_model):
        pairs = (
            SystemMessage.objects.outstanding()
            .filter(**{f"{message_path}__in": pks})
            .values_list(message_path, "pk")
        )
        for object_pk, message_pk in pairs:
            reaching[object_pk].add(message_pk)
    return reaching


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


def _subject_label(subject) -> str:
    if subject is None:
        return "Unknown subject"
    model = subject._meta.model
    kind = SUBJECT_KINDS.get(model)
    label = kind.label if kind else model._meta.verbose_name.title()
    return f"{label} · {subject}"


def _promql_context(message, subject) -> dict:
    """The context `promql.query_for` wants, filled in from the message's subject.

    `constraint_group` is a model field rather than a context key, and the fetch-failure
    handlers record neither the dataset nor the server name (they have no need to, the
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
        # server_label, not `.name`: name is nullable, and the metric labels this query
        # matches on use name-or-base_url. `.name` would yield no query for a nameless server.
        if isinstance(subject, ErddapServer):
            context["server"] = metrics.server_label(subject)
        elif isinstance(subject, ErddapDataset):
            context["server"] = metrics.server_label(subject.server)
        elif isinstance(subject, TimeSeries):
            context["server"] = metrics.server_label(subject.dataset.server)

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


def build_system_message_rows(obj, admin_site) -> list[SystemMessageRow]:
    """The sidebar for `obj`'s change page: gather, judge containment, and pre-render."""
    page_model = obj._meta.model
    message_pks = messages_reaching(page_model, [obj.pk]).get(obj.pk, set())
    messages = list(
        SystemMessage.objects.filter(pk__in=message_pks).select_related(
            "acknowledged_by",
            *_SUBJECT_SELECT_RELATED,
        ),
    )
    reach_by_message = compute_message_reach(messages)

    page_kind = SUBJECT_KINDS.get(page_model)
    reach_label = page_kind.plural if page_kind else "objects"

    rows = []
    for message in messages:
        subject = message.subject
        reach = reach_by_message.get(message.pk, _EMPTY_REACH)
        axis = reach.ids_along(page_model)
        spilled = axis - {obj.pk}

        promql = query_for(message.code, _promql_context(message, subject))

        rows.append(
            SystemMessageRow(
                message=message,
                subject_label=_subject_label(subject),
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

    reaching = messages_reaching(page_model, [obj.pk for obj in objs])
    message_pks = set().union(*reaching.values()) if reaching else set()
    messages = {message.pk: message for message in SystemMessage.objects.filter(pk__in=message_pks)}
    reach_by_message = compute_message_reach(messages.values())

    for obj in objs:
        contained = defaultdict(int)
        spilling = defaultdict(int)

        for message_pk in reaching.get(obj.pk, ()):
            message = messages[message_pk]
            reach = reach_by_message.get(message_pk, _EMPTY_REACH)
            if reach.ids_along(page_model) - {obj.pk}:
                subject_kind = SUBJECT_KINDS.get(message.subject_model)
                spilling[subject_kind.label.lower() if subject_kind else "other"] += 1
            else:
                contained[message.level] += 1

        obj._system_message_badge = SystemMessageBadge(  # noqa: SLF001 - carrier for the display fn
            contained=[(level, contained[level]) for level in _LEVEL_ORDER if contained.get(level)],
            spilling=sorted(spilling.items()),
        )

    return objs


# The annotation `system_message_status` sorts on. Named once so the display callable's
# `admin_order_field` and the queryset that has to supply it cannot fall out of step.
SYSTEM_MESSAGE_RANK = "system_message_rank"


def outstanding_messages_exist(page_model, level=None) -> Q | None:
    """Whether an outstanding message reaches a row of `page_model`, as correlated subqueries.

    `Exists` rather than a filter through the `system_messages` relations, because the chain is
    multi-valued: a join-based filter returns one row per matching message,
    so a platform with a message on its dataset *and* its server is listed twice. One
    `Exists` per path rather than one over all four OR'd together, because Postgres plans the
    OR'd form as a single many-way left join with an OR'd join filter (which no index can
    serve) while each path alone is an index lookup.

    The outstanding predicate comes from `SystemMessageQuerySet.outstanding()` rather than
    being rewritten here, so the filter and the sidebar cannot disagree about whether an
    acknowledged-then-recurring message still counts.
    """
    paths = _paths_for(page_model)
    if not paths:
        return None

    messages = SystemMessage.objects.outstanding()
    if level is not None:
        messages = messages.filter(level=level)

    reaches = Q()
    for message_path in paths:
        reaches |= Q(Exists(messages.filter(**{message_path: OuterRef("pk")})))
    return reaches


def _worst_severity_along(message_path):
    """The severity of the worst outstanding message reaching a row through one path."""
    severity = Case(
        *[
            When(level=level, then=Value(len(_LEVEL_ORDER) - index))
            for index, level in enumerate(_LEVEL_ORDER)
        ],
        default=Value(0),
        output_field=IntegerField(),
    )
    worst = (
        SystemMessage.objects.outstanding()
        .filter(**{message_path: OuterRef("pk")})
        .annotate(severity=severity)
        .order_by("-severity")
        .values("severity")[:1]
    )
    return Coalesce(Subquery(worst), Value(0), output_field=IntegerField())


def system_message_rank(page_model):
    """The severity of the worst outstanding message reaching a row, as a sortable number.

    `Level` is a CharField, so ordering by the column is alphabetical -- danger, info,
    warning -- which files the least alarming level in between the other two. Nothing on the
    page would give that away: the column just sorts wrongly and quietly. So severity is
    ranked explicitly, with 0 for a row nothing reaches so "None" sorts below every level.
    """
    paths = _paths_for(page_model)
    if not paths:
        return Value(0, output_field=IntegerField())

    ranks = [_worst_severity_along(message_path) for message_path in paths]
    if len(ranks) == 1:
        return ranks[0]
    return Greatest(*ranks)


@admin.display(description="System messages", ordering=SYSTEM_MESSAGE_RANK)
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


class SystemMessageListFilter(SimpleListFilter):
    """Filter a platform/timeseries/dataset changelist by what its chain is complaining about.

    Deliberately speaks the badge's language: it matches through the same `SUBJECT_KINDS`
    paths the sidebar gathers on, so a platform whose *server* is failing is matched here
    exactly as it is shown there. "None" therefore means nothing anywhere in the chain, not
    merely nothing attached to this row.
    """

    title = "system messages"
    parameter_name = "system_message"

    def lookups(self, request: Any, model_admin: Any) -> list[tuple[Any, str]]:
        levels = [(level.value, level.label) for level in _LEVEL_ORDER]
        return [("any", "Any outstanding"), *levels, ("none", "None")]

    def queryset(self, request: Any, queryset: QuerySet[Any]) -> QuerySet[Any] | None:
        value = self.value()
        if value not in {"any", "none", *SystemMessage.Level.values}:
            return queryset

        level = value if value in SystemMessage.Level.values else None
        reaching = outstanding_messages_exist(queryset.model, level)
        if reaching is None:
            return queryset
        return queryset.filter(~reaching if value == "none" else reaching)


class SystemMessageSidebarMixin:
    """Puts outstanding messages for a page's whole chain into Django's own right sidebar."""

    change_form_template = "admin/deployments/change_form.html"

    class Media:
        # Wires up the sidebar's PromQL "Copy" button and click-to-select-all. Declared here
        # (rather than only on `SystemMessageAdmin`) so it loads on admins that mix
        # this in (Platform, ErddapDataset, ErddapServer, TimeSeries) since any of them
        # can render a `.system-message-promql` block. `extend` defaults to True, so this
        # merges with each ModelAdmin's own base media (jquery, core.js, ...) rather than
        # replacing it.
        js = ["deployments/js/system_messages.js"]

    def get_changelist(self, request, **kwargs):
        return SystemMessageChangeList

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Supply the severity annotation the badge column sorts on.

        Added here rather than in each admin so the annotation and the column arrive together:
        an admin that lists the badge but forgot the annotation would raise on the first click
        of the column header. Skipped where the column is not listed, since the annotation
        costs one correlated subquery per path.
        """
        queryset = super().get_queryset(request)
        if system_message_status in self.list_display:
            queryset = queryset.annotate(**{SYSTEM_MESSAGE_RANK: system_message_rank(self.model)})
        return queryset

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = {**(extra_context or {})}
        obj = self.get_object(request, unquote(object_id))
        if obj is not None:
            extra_context["system_messages"] = build_system_message_rows(obj, self.admin_site)
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


class SystemMessageSubjectFilter(SimpleListFilter):
    """Filter the message list by which kind of thing the messages are about."""

    title = "subject type"
    parameter_name = "subject_type"

    def lookups(self, request: Any, model_admin: Any) -> list[tuple[Any, str]]:
        return [(kind.field, kind.label) for kind in SUBJECT_KINDS.values()]

    def queryset(self, request: Any, queryset: QuerySet[Any]) -> QuerySet[Any] | None:
        value = self.value()
        if value not in {kind.field for kind in SUBJECT_KINDS.values()}:
            return queryset
        return queryset.filter(**{f"{value}__isnull": False})


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
    list_filter = [SystemMessageStateFilter, "level", "code", SystemMessageSubjectFilter]
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

    # The only two fields a human is allowed to write.
    editable_fields = ("acknowledged_at", "acknowledged_by")

    class Media:
        # Same copy/select-all affordance as the sidebar's PromQL block, since
        # `promql_query` below renders the identical `.system-message-promql` markup.
        js = ["deployments/js/system_messages.js"]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        queryset = super().get_queryset(request)
        return queryset.select_related("acknowledged_by", *_SUBJECT_SELECT_RELATED)

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
        label = _subject_label(subject)
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

        block = format_html(
            "<div class='system-message-promql'>"
            "<pre style='white-space: pre-wrap; overflow-wrap: anywhere;'>{}</pre>"
            "<button type='button' class='button system-message-copy'>Copy</button>"
            "</div>",
            query,
        )

        url = explore_url(query)
        if not url:
            return block
        return format_html(
            "{}<a href='{}' rel='noreferrer'>Open in Grafana</a>",
            block,
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
