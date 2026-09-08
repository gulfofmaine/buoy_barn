"""Observable gauges describing how fresh the data is, read straight from the database.

Callbacks rather than values pushed from the refresh tasks: a counter the tasks increment
could never report a dataset that stopped being refreshed altogether, which is the failure
worth alerting on. Exactly one process may collect them, so they live in the
``export_metrics`` management command and its single-replica deployment.

``value_age`` is aggregated per platform rather than per timeseries: there are thousands of
those and they churn as series are retired, so per-series gauges would be large and unstable.

No callback may raise, an exception escaping one can stop collection for the whole
provider. See :func:`_observations`, which every callback goes through.
"""

import logging

logger = logging.getLogger(__name__)

# Fallback for a label whose source column is null, so `str(None)` never puts the literal
# "None" on a time series.
UNKNOWN = "unknown"


def _label(value) -> str:
    """Coerce a possibly-null database value into a usable attribute value."""
    return str(value) if value else UNKNOWN


def _server_label(name, base_url) -> str:
    """The ``erddap.server`` value for these column values.

    Delegates to :func:`buoy_barn.observability.metrics.server_label` because the refresh
    path labels the same server through it. The two disagreeing breaks the
    ``constraint_group.info`` join for every server whose ``name`` is null.
    """
    from .metrics import server_label  # noqa: PLC0415

    return server_label(name, base_url)


def _observations(callback):
    """Run a gauge callback safely, returning [] on any failure.

    Closes stale database connections first: this is a long-lived process and
    ``CONN_MAX_AGE`` is not set, so the server may have dropped the connection underneath it.
    """
    from django.db import close_old_connections  # noqa: PLC0415

    try:
        close_old_connections()
        return list(callback())
    except Exception:
        logger.exception("Freshness gauge callback failed; skipping this collection cycle")
        return []


def _dataset_refresh_ages():
    """Seconds since each dataset was last refresh-attempted."""
    from django.utils import timezone  # noqa: PLC0415
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    from deployments.models import ErddapDataset  # noqa: PLC0415

    now = timezone.now()
    rows = ErddapDataset.objects.filter(refresh_attempted__isnull=False).values_list(
        "server__name",
        "server__base_url",
        "name",
        "refresh_attempted",
    )
    return [
        Observation(
            max((now - refresh_attempted).total_seconds(), 0.0),
            {
                "erddap.server": _server_label(server, base_url),
                "erddap.dataset": _label(dataset),
            },
        )
        for server, base_url, dataset, refresh_attempted in rows
    ]


def _datasets_never_refreshed():
    """Datasets that have never been refresh-attempted, by server."""
    from django.db.models import Count  # noqa: PLC0415
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    from deployments.models import ErddapDataset  # noqa: PLC0415

    rows = (
        ErddapDataset.objects.filter(refresh_attempted__isnull=True)
        .values("server__name", "server__base_url")
        .annotate(total=Count("id"))
    )
    return [
        Observation(
            row["total"],
            {"erddap.server": _server_label(row["server__name"], row["server__base_url"])},
        )
        for row in rows
    ]


def _timeseries_value_ages():
    """Age of the newest and oldest observation per platform, server and series type.

    A single aggregate query, unlike `more_thank_a_week_old`, which loads every stale series
    into Python.
    """
    from django.db.models import Max, Min  # noqa: PLC0415
    from django.utils import timezone  # noqa: PLC0415
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    from deployments.models import TimeSeries  # noqa: PLC0415

    now = timezone.now()
    rows = (
        TimeSeries.objects.filter(active=True, end_time__isnull=True, value_time__isnull=False)
        .values(
            "platform__name",
            "dataset__server__name",
            "dataset__server__base_url",
            "timeseries_type",
        )
        .annotate(newest=Max("value_time"), oldest=Min("value_time"))
    )

    observations = []
    for row in rows:
        attributes = {
            "platform": _label(row["platform__name"]),
            "erddap.server": _server_label(
                row["dataset__server__name"],
                row["dataset__server__base_url"],
            ),
            "timeseries.type": _label(row["timeseries_type"]),
        }
        # "newest" is the freshest reading, so its age is the smallest -- the number that
        # answers "is this buoy reporting?".
        observations.append(
            Observation(
                max((now - row["newest"]).total_seconds(), 0.0),
                {**attributes, "agg": "min"},
            ),
        )
        observations.append(
            Observation(
                max((now - row["oldest"]).total_seconds(), 0.0),
                {**attributes, "agg": "max"},
            ),
        )
    return observations


# ``state`` label value -> the filter that counts it, and the annotation alias holding the
# count. Every alias needs its ``_count`` suffix: an ``annotate(active=...)`` shadows
# ``TimeSeries.active``, so a later ``Q(active=False)`` resolves to the annotation and
# Postgres rejects the nested aggregate, which silently published nothing at all.
_TIMESERIES_STATES = (
    ("active", "active_count", {"active": True, "end_time__isnull": True}),
    ("inactive", "inactive_count", {"active": False}),
    ("retired", "retired_count", {"end_time__isnull": False}),
    ("never_populated", "never_populated_count", {"value_time__isnull": True}),
)


def _timeseries_counts():
    """How many timeseries are in each state, by server.

    The states overlap on purpose (a retired series is also inactive) so they are counted
    independently rather than partitioned, and do not sum to the server's total.
    """
    from django.db.models import Count, Q  # noqa: PLC0415
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    from deployments.models import TimeSeries  # noqa: PLC0415

    rows = TimeSeries.objects.values("dataset__server__name", "dataset__server__base_url").annotate(
        **{alias: Count("id", filter=Q(**filters)) for _state, alias, filters in _TIMESERIES_STATES},
    )

    return [
        Observation(
            row[alias],
            {
                "erddap.server": _server_label(
                    row["dataset__server__name"],
                    row["dataset__server__base_url"],
                ),
                "state": state,
            },
        )
        for row in rows
        for state, alias, _filters in _TIMESERIES_STATES
    ]


# Longest `constraints` label value the info metric will emit, so a pathological constraints
# dict cannot bloat it without limit.
MAX_CONSTRAINTS_LABEL = 200


def _constraints_label(constraints) -> str:
    """Human-readable constraints for the lookup metric, truncated if absurdly long."""
    from .metrics import NO_CONSTRAINTS, canonical_constraints  # noqa: PLC0415

    if not constraints:
        return NO_CONSTRAINTS
    text = canonical_constraints(constraints)
    if len(text) > MAX_CONSTRAINTS_LABEL:
        return text[: MAX_CONSTRAINTS_LABEL - 1] + "\u2026"
    return text


def _constraint_group_info():
    """Map each `constraint_group` id back to the constraints it stands for.

    The other half of the opaque hash on ``buoybarn.erddap.outcome``: the standard Prometheus
    info-metric pattern, always 1, carrying the readable constraints as a joinable label.

    That JSON on a label is a deliberate exception to the cardinality rule in
    :mod:`buoy_barn.observability.metrics`. Here there is one series per (dataset, group),
    rewritten once per cycle by the single exporter, so the cost is label length rather than
    series count.

    Selects through ``TimeSeries.objects.refreshable()``, as
    ``group_timeseries_by_constraint_and_type`` does. Sharing a filter does not by itself keep
    the *key* in step, so a test asserts both produce identical ``(dataset, group_id)`` sets.
    """
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    from deployments.models import TimeSeries  # noqa: PLC0415

    from .metrics import constraint_group_id  # noqa: PLC0415

    # Grouped in Python: calling group_timeseries_by_constraint_and_type() per dataset would
    # be ~384 queries per cycle.
    rows = TimeSeries.objects.refreshable().values(
        "dataset__server__name",
        "dataset__server__base_url",
        "dataset__name",
        "constraints",
        "timeseries_type",
    )

    seen = {}
    for row in rows:
        group_id = constraint_group_id(row["constraints"])
        key = (
            _server_label(row["dataset__server__name"], row["dataset__server__base_url"]),
            _label(row["dataset__name"]),
            group_id,
            _label(row["timeseries_type"]),
        )
        if key not in seen:
            seen[key] = _constraints_label(row["constraints"])

    return [
        Observation(
            1,
            {
                "erddap.server": server,
                "erddap.dataset": dataset,
                "constraint_group": group_id,
                "timeseries.type": timeseries_type,
                "constraints": constraints,
            },
        )
        for (server, dataset, group_id, timeseries_type), constraints in seen.items()
    ]


def _celery_queue_depths():
    """Length of each Celery queue on the Redis broker.

    Sampled here rather than from the workers because reading it from N prefork children
    would report the same backlog N times.
    """
    from django.conf import settings  # noqa: PLC0415
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if not broker_url:
        return []

    import redis  # noqa: PLC0415

    client = redis.Redis.from_url(broker_url)
    try:
        # Celery stores each queue as a Redis list named after the queue.
        return [
            Observation(client.llen(queue), {"celery.queue": queue}) for queue in _queue_names(settings)
        ]
    finally:
        client.close()


def _queue_names(settings) -> list[str]:
    names = {getattr(settings, "CELERY_TASK_DEFAULT_QUEUE", None) or "celery"}
    for queue in getattr(settings, "CELERY_TASK_QUEUES", None) or ():
        name = getattr(queue, "name", None) or (queue if isinstance(queue, str) else None)
        if name:
            names.add(str(name))
    return sorted(names)


# Gauge name -> (unit, description, callback).
GAUGES = {
    "buoybarn.dataset.refresh_age": (
        "s",
        "Seconds since a dataset refresh was last attempted",
        _dataset_refresh_ages,
    ),
    "buoybarn.dataset.never_refreshed": (
        "{dataset}",
        "Datasets that have never had a refresh attempted",
        _datasets_never_refreshed,
    ),
    "buoybarn.timeseries.value_age": (
        "s",
        "Age of the newest (agg=min) and oldest (agg=max) observation per platform",
        _timeseries_value_ages,
    ),
    "buoybarn.timeseries.count": (
        "{timeseries}",
        "Timeseries per server, by state",
        _timeseries_counts,
    ),
    "buoybarn.celery.queue.depth": (
        "{task}",
        "Tasks waiting on each Celery queue",
        _celery_queue_depths,
    ),
    "buoybarn.erddap.constraint_group.info": (
        "1",
        "Lookup from a constraint_group id to the constraints it stands for; always 1",
        _constraint_group_info,
    ),
}


def register(meter) -> list:
    """Create every observable gauge on ``meter``. Returns the created instruments.

    The caller must keep the instruments alive: some SDK versions hold only weak references
    to callbacks, and letting them be collected silently stops collection.
    """
    instruments = []
    for name, (unit, description, callback) in GAUGES.items():
        instruments.append(
            meter.create_observable_gauge(
                name,
                callbacks=[lambda options, cb=callback: _observations(cb)],
                unit=unit,
                description=description,
            ),
        )
    logger.info("Registered %d freshness gauges", len(instruments))
    return instruments
