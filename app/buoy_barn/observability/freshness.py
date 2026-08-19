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

#: Fallback for a label whose source column is null. `ErddapServer.name` is nullable, and
#: str(None) would put the literal "None" on a time series.
UNKNOWN = "unknown"


def _label(value) -> str:
    """Coerce a possibly-null database value into a usable attribute value."""
    return str(value) if value else UNKNOWN


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
        "name",
        "refresh_attempted",
    )
    return [
        Observation(
            max((now - refresh_attempted).total_seconds(), 0.0),
            {"erddap.server": _label(server), "erddap.dataset": _label(dataset)},
        )
        for server, dataset, refresh_attempted in rows
    ]


def _datasets_never_refreshed():
    """Datasets that have never been refresh-attempted, by server."""
    from django.db.models import Count  # noqa: PLC0415
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    from deployments.models import ErddapDataset  # noqa: PLC0415

    rows = (
        ErddapDataset.objects.filter(refresh_attempted__isnull=True)
        .values("server__name")
        .annotate(total=Count("id"))
    )
    return [Observation(row["total"], {"erddap.server": _label(row["server__name"])}) for row in rows]


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
        .values("platform__name", "dataset__server__name", "timeseries_type")
        .annotate(newest=Max("value_time"), oldest=Min("value_time"))
    )

    observations = []
    for row in rows:
        attributes = {
            "platform": _label(row["platform__name"]),
            "erddap.server": _label(row["dataset__server__name"]),
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


def _timeseries_counts():
    """How many timeseries are in each state, by server."""
    from django.db.models import Count, Q  # noqa: PLC0415
    from opentelemetry.metrics import Observation  # noqa: PLC0415

    from deployments.models import TimeSeries  # noqa: PLC0415

    rows = TimeSeries.objects.values("dataset__server__name").annotate(
        active=Count("id", filter=Q(active=True, end_time__isnull=True)),
        inactive=Count("id", filter=Q(active=False)),
        retired=Count("id", filter=Q(end_time__isnull=False)),
        never_populated=Count("id", filter=Q(value_time__isnull=True)),
    )

    states = ("active", "inactive", "retired", "never_populated")
    return [
        Observation(
            row[state],
            {"erddap.server": _label(row["dataset__server__name"]), "state": state},
        )
        for row in rows
        for state in states
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
