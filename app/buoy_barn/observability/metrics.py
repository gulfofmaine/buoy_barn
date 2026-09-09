"""The metrics facade every call site imports.

Design rules, in priority order:

1. Never raise. Instrumentation that can break a refresh is worse than no instrumentation.
2. Be free when switched off. With no OTLP endpoint configured, each function returns after
   one dict lookup. See :mod:`buoy_barn.observability.bootstrap`.
3. Keep cardinality bounded. Attribute values are validated against a bounded set, so a
   future call site cannot start labelling metrics with an error string or a primary key;
   unknown values collapse to ``"other"``. Vocabularies owned elsewhere are read from their
   owner (see :func:`erddap_outcomes` and :func:`timeseries_types`).

``erddap.dataset`` appears on the *counter* only. There are ~384 datasets across ~15
servers, so multiplying that by a histogram's bucket count would be tens of thousands of
series. Latency is tracked per server (which is the unit you act on anyway), you throttle
or contact a server, not a dataset.
"""

import hashlib
import json
import logging
import os
import re
import time
from contextlib import contextmanager

from . import bootstrap

logger = logging.getLogger(__name__)

# Sentinel for an attribute value outside its declared set.
OTHER = "other"

# Attribute value for a group with no ERDDAP constraints at all -- the common case, and far
# more readable in a dashboard than the hash of an empty dict.
NO_CONSTRAINTS = "none"

# A group id is a hash, so it cannot be validated against a frozenset like every other
# attribute; its shape is checked instead, which still keeps free text off labels.
_GROUP_ID_RE = re.compile(r"^[0-9a-f]{8}$")

# 8 hex characters is ~4 billion values -- ample for the low thousands of real groups, and
# short enough to read in a dashboard.
_GROUP_ID_LENGTH = 8

# For a server with neither a name nor a base URL, so a half-built row from a test or a
# migration cannot put the literal "None" on a time series.
UNKNOWN_SERVER = "unknown"


def server_label(server, base_url=None) -> str:
    """The ``erddap.server`` attribute value for one server, however it was loaded.

    Every metric in this package must agree on what identifies a server, or the
    ``buoybarn.erddap.constraint_group.info`` join silently returns nothing. The refresh path
    holds an ``ErddapServer`` instance while the exporter's gauges hold plain column values
    from ``.values()``, so this accepts either.

    Precedence mirrors ``ErddapServer.__str__`` (name, else base URL) so the label
    matches what the logs and the admin call the same server.
    """
    name = getattr(server, "name", server)
    url = getattr(server, "base_url", base_url)
    if name:
        return str(name)
    if url:
        return str(url)
    return UNKNOWN_SERVER


def canonical_constraints(constraints) -> str:
    """Serialise an ERDDAP constraints mapping so equal constraints always match.

    ``sort_keys`` makes this stable: the same constraints built in a different order
    must produce the same string, or the same group would be counted under two ids.
    """
    return json.dumps(constraints or {}, sort_keys=True, separators=(",", ":"), default=str)


def constraint_group_id(constraints) -> str:
    """Short stable id for one ERDDAP constraint group.

    A dataset is fetched once per ``(constraints, timeseries_type)`` group, so one group can
    fail while its siblings succeed. This id makes it distinguishable on
    ``buoybarn.erddap.outcome`` without putting the unbounded constraints JSON on a hot
    counter.

    Being opaque, it is only useful alongside ``buoybarn.erddap.constraint_group.info`` in
    :mod:`buoy_barn.observability.freshness`. Both sides call this function, which is what
    keeps them joinable.
    """
    if not constraints:
        return NO_CONSTRAINTS
    digest = hashlib.sha256(canonical_constraints(constraints).encode("utf-8")).hexdigest()
    return digest[:_GROUP_ID_LENGTH]


CELERY_STATES = frozenset({"started", "success", "failure", "retry", "revoked", OTHER})

PING_OUTCOMES = frozenset({"ok", "error", OTHER})

LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical", OTHER})

# Vocabularies owned by ``deployments``, cached after the first lookup.
#
# Resolution has to be lazy: this module is imported while Django builds the ``LOGGING``
# setting (via :mod:`buoy_barn.observability.log_metrics`), long before the app registry
# exists, so importing a model or a task at module scope would break startup.
_vocabularies: dict[str, frozenset[str]] = {}


def _resolved(name: str, load) -> frozenset[str]:
    """Cache and return one lazily-loaded vocabulary, including ``OTHER``."""
    cached = _vocabularies.get(name)
    if cached is not None:
        return cached
    try:
        resolved = frozenset(load()) | {OTHER}
    except Exception:
        # Not cached, so a later call can still succeed once the app registry is ready.
        logger.debug("Could not resolve the %s vocabulary", name, exc_info=True)
        return frozenset({OTHER})
    _vocabularies[name] = resolved
    return resolved


def erddap_outcomes() -> frozenset[str]:
    """Outcome of one ERDDAP fetch, as declared by the code that produces them.

    A new handler branch earns its own outcome if it logs at ERROR: folding it into
    ``no_rows`` would hide a misconfiguration behind a value dashboards treat as harmless.
    See ``BENIGN_OUTCOMES`` alongside the declaration.
    """

    def load():
        from deployments.tasks.outcomes import OUTCOMES  # noqa: PLC0415

        return OUTCOMES

    return _resolved("erddap outcome", load)


def timeseries_types() -> frozenset[str]:
    """``TimeSeries.timeseries_type`` choices, plus "unknown" for an unsupplied one."""

    def load():
        from deployments.models import TimeSeries  # noqa: PLC0415

        return set(TimeSeries.TimeSeriesType.values) | {"unknown"}

    return _resolved("timeseries type", load)


def _bounded(value, allowed: frozenset[str]) -> str:
    """Coerce ``value`` to a member of ``allowed``, collapsing anything else to "other"."""
    text = str(value) if value is not None else OTHER
    if text in allowed:
        return text
    logger.debug("Unexpected metric attribute %r; recording as %r", text, OTHER)
    return OTHER


def _bounded_group_id(value) -> str:
    """Validate a constraint group id by shape, since a hash cannot be enumerated."""
    if not value:
        return NO_CONSTRAINTS
    text = str(value)
    if text == NO_CONSTRAINTS or _GROUP_ID_RE.match(text):
        return text
    logger.debug("Unexpected constraint group id %r; recording as %r", text, OTHER)
    return OTHER


def sentry_mirror_enabled() -> bool:
    """Should a small allow-list of counters also go to Sentry Application Metrics?

    Off by default: Sentry bills Application Metrics like logs, and span attributes already
    cover most of what this would buy. Sentry cannot ingest OTLP, hence a separate call
    rather than another exporter.
    """
    return os.environ.get("BUOY_BARN_SENTRY_METRIC_MIRROR", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class _Instruments:
    """The instrument set for one process, built once per pid."""

    def __init__(self, meter) -> None:
        self.erddap_duration = meter.create_histogram(
            "buoybarn.erddap.request.duration",
            unit="s",
            description="Wall time of one ERDDAP fetch, by server and outcome",
        )
        self.erddap_rows = meter.create_histogram(
            "buoybarn.erddap.request.rows",
            unit="{row}",
            description="Rows returned by an ERDDAP fetch; zero means a successful empty response",
        )
        self.erddap_outcome = meter.create_counter(
            "buoybarn.erddap.outcome",
            description="ERDDAP fetch outcomes, by server, dataset and outcome",
        )
        self.task_count = meter.create_counter(
            "buoybarn.celery.task.count",
            description="Celery task transitions, by task and state",
        )
        self.task_duration = meter.create_histogram(
            "buoybarn.celery.task.duration",
            unit="s",
            description="Celery task execution time, by task and terminal state",
        )
        self.task_in_progress = meter.create_up_down_counter(
            "buoybarn.celery.task.in_progress",
            description="Celery tasks currently executing, by task",
        )
        self.task_queue_latency = meter.create_histogram(
            "buoybarn.celery.task.queue_latency",
            unit="s",
            description="Time between a task being published and starting to run",
        )
        self.healthcheck_ping = meter.create_counter(
            "buoybarn.healthcheck.ping",
            description="Healthchecks.io pings attempted, by monitor and outcome",
        )
        self.log_records = meter.create_counter(
            "buoybarn.log.records",
            description="Log records emitted, by logger and level",
        )


class _InstrumentCache:
    """Holds the instrument set and the pid it belongs to.

    Instruments belong to a provider, and the provider is rebuilt after ``fork()``, so the
    cache is invalidated by pid just like the provider itself.
    """

    def __init__(self) -> None:
        self.instruments: _Instruments | None = None
        self.pid: int | None = None
        # PID whose instrument build already failed, so it is not retried. Logging that
        # failure runs :class:`~buoy_barn.observability.log_metrics.MetricsLogHandler`, which
        # comes straight back here; without this, one failure recurses per log record.
        self.failed_pid: int | None = None


_cache = _InstrumentCache()


def instruments() -> _Instruments | None:
    """Instrument set for this process, or None when metrics are switched off.

    Never raises. Callers call this *outside* their own ``try``, so anything escaping here
    escapes into the refresh path.
    """
    pid = os.getpid()
    if _cache.pid == pid and _cache.instruments is not None:
        return _cache.instruments

    if _cache.failed_pid == pid:
        return None

    # Deliberately *not* memoized as a failure: acquiring a meter can fail transiently (a
    # `shutdown()` racing this call on another thread used to surface here as an AttributeError)
    # and a process that is merely mid-shutdown is not broken.
    try:
        meter = bootstrap.get_meter()
    except Exception:
        logger.debug("Could not acquire a meter; skipping this recording", exc_info=True)
        return None

    if meter is None:
        return None

    try:
        built = _Instruments(meter)
    except Exception:
        # Remembered *before* logging, so recording the log record below finds a switched-off
        # layer rather than trying to build instruments again.
        _cache.failed_pid = pid
        logger.exception("Could not create metric instruments; metrics are disabled")
        return None

    _cache.instruments = built
    _cache.pid = pid
    return built


def reset_for_testing() -> None:
    """Drop the cached instrument set so a test can install a fresh provider."""
    _cache.instruments = None
    _cache.pid = None
    _cache.failed_pid = None


def _mirror_to_sentry(key: str, attributes: dict) -> None:
    if not sentry_mirror_enabled():
        return
    try:
        import sentry_sdk  # noqa: PLC0415

        sentry_sdk.metrics.count(key, 1, attributes=attributes)
    except Exception:
        logger.debug("Could not mirror %s to Sentry metrics", key, exc_info=True)


def record_erddap_request(  # noqa: PLR0913 - one metric per dimension it records
    server,
    dataset,
    duration_s: float | None,
    outcome: str,
    rows: int | None = None,
    constraint_group: str | None = None,
    timeseries_type: str | None = None,
) -> None:
    """Record one ERDDAP fetch: its duration, row count and outcome.

    ``erddap.dataset``, ``constraint_group`` and ``timeseries_type`` land on the **counter
    only**; on a histogram each would multiply by the bucket count.
    """
    inst = instruments()
    if inst is None:
        return

    try:
        safe_outcome = _bounded(outcome, erddap_outcomes())
        server_name = server_label(server)

        inst.erddap_duration.record(
            max(float(duration_s), 0.0) if duration_s is not None else 0.0,
            {"erddap.server": server_name, "outcome": safe_outcome},
        )
        if rows is not None:
            inst.erddap_rows.record(max(int(rows), 0), {"erddap.server": server_name})

        attributes = {
            "erddap.server": server_name,
            "erddap.dataset": str(dataset),
            "outcome": safe_outcome,
            # Always present, even when a caller supplies neither, so a query never meets the
            # same metric both with and without these labels.
            "constraint_group": _bounded_group_id(constraint_group),
            "timeseries.type": _bounded(timeseries_type or "unknown", timeseries_types()),
        }
        inst.erddap_outcome.add(1, attributes)
        if safe_outcome != "success":
            _mirror_to_sentry("buoybarn.erddap.outcome", attributes)
    except Exception:
        logger.debug("Failed to record ERDDAP metrics", exc_info=True)


# Classifies an exception that escapes an :func:`erddap_request` block. Keyed on the class
# *name* so this module stays independent of ``deployments``, which owns ``BackoffError``.
_OUTCOME_BY_EXCEPTION = {
    "BackoffError": "backoff",
    "TimeoutException": "timeout",
    "ConnectError": "timeout",
    "ConnectTimeout": "timeout",
    "ReadTimeout": "timeout",
    # Celery's soft time limit landing mid-fetch: the run ran out of time, which is a timeout
    # rather than a surprise. Without this it would count as "unknown_error" and hide the
    # slow-dataset signal behind the bucket reserved for genuinely unclassified failures.
    "SoftTimeLimitExceeded": "timeout",
    "OSError": "os_error",
}


class OutcomeTracker:
    """Mutable outcome holder handed out by :func:`erddap_request`."""

    def __init__(self) -> None:
        self.outcome = "success"
        self.rows: int | None = None
        # Did a call site name the outcome? Tracked separately from its *value*, since
        # "success" is both the default and a real outcome a call site sets. Testing
        # `outcome == "success"` conflates the two, and an exception raised after a
        # successful fetch would then rewrite it into `unknown_error`.
        self.explicit = False

    def set(self, outcome: str, rows: int | None = None) -> None:
        self.outcome = outcome
        self.explicit = True
        if rows is not None:
            self.rows = rows


@contextmanager
def erddap_request(server, dataset, constraint_group=None, timeseries_type=None):
    """Time an ERDDAP fetch and record its outcome on the way out.

    Used as a context manager so the call site stays a single ``with`` line even though
    the outcome is only known inside the existing ``except`` branches::

        with metrics.erddap_request(server, dataset) as outcome:
            ...
            except TimeoutException:
                outcome.set("timeout")
    """
    tracker = OutcomeTracker()
    started = time.monotonic()
    try:
        yield tracker
    except BaseException as exc:
        # An unnamed outcome here means the fetch itself did not succeed, most importantly
        # BackoffError, which the 408/429 handlers raise from inside the caller's own
        # `except HTTPError` branch. See `OutcomeTracker.explicit` for why only unnamed ones.
        if not tracker.explicit:
            tracker.set(_OUTCOME_BY_EXCEPTION.get(type(exc).__name__, "unknown_error"))
        raise
    finally:
        record_erddap_request(
            server,
            dataset,
            time.monotonic() - started,
            tracker.outcome,
            tracker.rows,
            constraint_group=constraint_group,
            timeseries_type=timeseries_type,
        )


def record_task(task_name: str, state: str, duration_s: float | None = None) -> None:
    """Record a Celery task transition, and its duration for terminal states."""
    inst = instruments()
    if inst is None:
        return

    try:
        attributes = {"celery.task": str(task_name), "celery.state": _bounded(state, CELERY_STATES)}
        inst.task_count.add(1, attributes)
        if duration_s is not None:
            inst.task_duration.record(max(float(duration_s), 0.0), attributes)
        if attributes["celery.state"] in {"failure", "revoked"}:
            _mirror_to_sentry("buoybarn.celery.task.count", attributes)
    except Exception:
        logger.debug("Failed to record Celery task metrics", exc_info=True)


def record_task_queue_latency(task_name: str, seconds: float) -> None:
    """Record how long a task waited between being published and starting."""
    inst = instruments()
    if inst is None:
        return

    try:
        inst.task_queue_latency.record(
            max(float(seconds), 0.0),
            {"celery.task": str(task_name)},
        )
    except Exception:
        logger.debug("Failed to record Celery queue latency", exc_info=True)


def task_in_progress(task_name: str, delta: int) -> None:
    """Adjust the gauge of currently-executing tasks by ``delta``."""
    inst = instruments()
    if inst is None:
        return

    try:
        inst.task_in_progress.add(int(delta), {"celery.task": str(task_name)})
    except Exception:
        logger.debug("Failed to record Celery in-progress metrics", exc_info=True)


def record_healthcheck_ping(monitor: str, outcome: str) -> None:
    """Record a Healthchecks.io ping attempt.

    Every ping call site swallows ``requests.RequestException``, so without this a monitor
    that stopped being pinged looks healthy until the monitor itself alerts.
    """
    inst = instruments()
    if inst is None:
        return

    try:
        inst.healthcheck_ping.add(
            1,
            {"monitor": str(monitor), "outcome": _bounded(outcome, PING_OUTCOMES)},
        )
    except Exception:
        logger.debug("Failed to record healthcheck ping metrics", exc_info=True)


def record_log(logger_name: str, level: str) -> None:
    """Count one log record, by logger and level.

    The backstop for the pipeline's swallowed errors: ``handle_http_errors`` and friends log
    and return rather than raising, so Celery reports success even when every fetch failed.
    """
    inst = instruments()
    if inst is None:
        return

    try:
        inst.log_records.add(
            1,
            {"logger": str(logger_name), "level": _bounded(str(level).lower(), LOG_LEVELS)},
        )
    except Exception:
        logger.debug("Failed to record log metrics", exc_info=True)
