"""Observable gauges describing how fresh the data is, read straight from the database.

These are *observable* (callback-driven) gauges rather than values pushed from the refresh
tasks, because they describe state rather than events: "dataset X was last refreshed N
seconds ago" is a fact about the database, true whether or not anything ran recently. A
counter incremented by the tasks could never report a dataset that stopped being refreshed
altogether -- which is precisely the failure worth alerting on.

They must be collected by exactly **one** process, so they live in the ``export_metrics``
management command and its single-replica deployment. Two replicas would report every gauge
twice.

Cardinality: ``refresh_age`` is per dataset (~384 stable series -- "which dataset is stale"
is the question being asked), but ``value_age`` is aggregated **per platform**, not per
timeseries. There are thousands of timeseries and they churn as series are retired, so
per-series gauges would be both large and unstable; the admin already shows per-series
detail.

Every callback runs on the SDK's exporter thread and must therefore never raise: an
exception escaping an observable-gauge callback can stop collection for the whole provider.
Each one closes stale database connections first, since this is a long-lived process and
``CONN_MAX_AGE`` is not set.
"""

import logging

logger = logging.getLogger(__name__)

#: Fallback for a label whose source column is null, so that str(None) never puts the literal
#: "None" on a time series.
UNKNOWN = "unknown"


def _label(value) -> str:
    """Coerce a possibly-null database value into a usable attribute value."""
    return str(value) if value else UNKNOWN


def _server_label(name, base_url) -> str:
    """The ``erddap.server`` value for these column values.

    Delegates to :func:`buoy_barn.observability.metrics.server_label` rather than formatting
    the name here, because the refresh path labels the same server through that function. If
    the two ever disagree -- and they did, when this module used the name alone while the
    counter used ``str(server)`` -- the ``constraint_group.info`` join returns nothing for
    every server whose ``name`` is null.
    """
    from .metrics import server_label  # noqa: PLC0415

    return server_label(name, base_url)


def _observations(callback):
    """Run a gauge callback safely, returning [] on any failure.

    Wraps three concerns that every callback shares: dropping database connections that
    the server may have closed under a long-lived process, converting failures into "no
    data this cycle" rather than a crashed exporter thread, and keeping the callbacks
    themselves readable.
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

    A single aggregate query -- deliberately not the row-by-row iteration used by
    `more_thank_a_week_old`, which loads every stale series into Python.
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
        # "newest" is the freshest reading, so its age is the smallest -- that is the
        # number that answers "is this buoy reporting?".
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


#: ``state`` label value -> the filter that counts it, and the annotation alias holding the
#: count. The aliases must not collide with a model field name: an ``annotate(active=...)``
#: shadows ``TimeSeries.active``, so a later ``Q(active=False)`` resolves to the annotation
#: and Postgres rejects the nested aggregate -- which is how this gauge silently published
#: nothing at all. Hence the ``_count`` suffix on every alias.
_TIMESERIES_STATES = (
    ("active", "active_count", {"active": True, "end_time__isnull": True}),
    ("inactive", "inactive_count", {"active": False}),
    ("retired", "retired_count", {"end_time__isnull": False}),
    ("never_populated", "never_populated_count", {"value_time__isnull": True}),
)


def _timeseries_counts():
    """How many timeseries are in each state, by server.

    The states overlap on purpose: a retired series is also inactive, and a never-populated
    one may be either. Each is the answer to its own question ("how much of this server have
    we given up on?", "how much never worked?"), so they are counted independently rather
    than partitioned.
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


#: Longest `constraints` label value the info metric will emit. The whole point of the metric
#: is that the JSON lives on one bounded series rather than a hot counter, but a pathological
#: constraints dict should still not be able to bloat it without limit.
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

    ``buoybarn.erddap.outcome`` is labelled with an opaque 8-character hash so that a failing
    constraint group is distinguishable from its healthy siblings without the unbounded
    constraints JSON ending up on a hot counter. That hash is useless on its own, so this is
    the other half: the standard Prometheus info-metric pattern, always 1, carrying the
    readable constraints as a label to be joined onto a failure panel.

    Putting the JSON on a label here is a deliberate exception to the rule stated in
    :mod:`buoy_barn.observability.metrics`. The rule exists because that JSON on a counter
    multiplies with every outcome and every request; here there is exactly one series per
    (dataset, group), it is rewritten once per collection cycle, and the exporter is the only
    process publishing it. The cost is label *value* length, not series count.

    Deliberately uses the same ``active=True, end_time IS NULL`` filter as
    ``group_timeseries_by_constraint_and_type``, so the groups described here are exactly the
    groups the refresh path actually fetches.
    """
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    from deployments.models import TimeSeries  # noqa: PLC0415

    from .metrics import constraint_group_id  # noqa: PLC0415

    # One query, grouped in Python. Walking datasets and calling
    # group_timeseries_by_constraint_and_type() per dataset would be ~384 queries per cycle.
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

    Sampled here rather than from the workers because it must be single-writer: reading it
    from N prefork children would report the same backlog N times.
    """
    from django.conf import settings  # noqa: PLC0415
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if not broker_url:
        return []

    import redis  # noqa: PLC0415

    client = redis.Redis.from_url(broker_url)
    try:
        # Celery stores each queue as a Redis list named after the queue. Only the default
        # queue is configured (there is no task_routes), but read whatever exists.
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


#: Gauge name -> (unit, description, callback).
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

    The instruments must be kept alive by the caller; the SDK only holds weak references
    to callbacks in some versions, and letting them be collected silently stops collection.
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
