"""The metrics facade every call site imports.

Design rules, in priority order:

1. **Never raise.** Instrumentation that can break a refresh is worse than no
   instrumentation. Every public function swallows its own errors and logs at most once.
2. **Be free when switched off.** With no OTLP endpoint configured, each function returns
   after one dict lookup. See :mod:`buoy_barn.observability.bootstrap`.
3. **Keep cardinality bounded.** Attribute values are validated against frozensets
   declared here, so a future call site cannot quietly start labelling metrics with an
   ERDDAP error string, a ``constraints`` blob, or a primary key. Unknown values collapse
   to ``"other"`` rather than creating a new time series.

Cardinality note: ``erddap.dataset`` appears on the *counter* only, never on a histogram.
There are ~384 datasets across ~15 servers; multiplying that by a histogram's bucket count
would be tens of thousands of series from a single metric. Latency is therefore tracked
per server -- the unit you actually act on, since you throttle or contact a server, not a
dataset -- while per-dataset detail lives on the cheap counter.
"""

import logging
import os
import time
from contextlib import contextmanager

from . import bootstrap

logger = logging.getLogger(__name__)

#: Sentinel for an attribute value outside its declared set.
OTHER = "other"

#: Outcome of one ERDDAP fetch. Mirrors the branches in ``deployments.tasks``.
ERDDAP_OUTCOMES = frozenset(
    {
        "success",
        "no_rows",
        "empty_dataframe",
        "not_found",
        "forbidden",
        "timeout",
        "backoff",
        "time_range_retired",
        "unrecognized_variable",
        "unrecognized_constraint",
        "server_error",
        "unknown_error",
        "os_error",
        "value_error",
        OTHER,
    },
)

CELERY_STATES = frozenset({"started", "success", "failure", "retry", "revoked", OTHER})

PING_OUTCOMES = frozenset({"ok", "error", OTHER})

LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical", OTHER})


def _bounded(value, allowed: frozenset[str]) -> str:
    """Coerce ``value`` to a member of ``allowed``, collapsing anything else to "other"."""
    text = str(value) if value is not None else OTHER
    if text in allowed:
        return text
    logger.debug("Unexpected metric attribute %r; recording as %r", text, OTHER)
    return OTHER


def sentry_mirror_enabled() -> bool:
    """Should a small allow-list of counters also go to Sentry Application Metrics?

    Off by default. Sentry cannot ingest OTLP metrics at all, so this is a genuinely
    separate call rather than another exporter, and Sentry bills Application Metrics like
    logs. Span attributes already cover most of what this would buy.
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


_cache = _InstrumentCache()


def instruments() -> _Instruments | None:
    """Instrument set for this process, or None when metrics are switched off."""
    pid = os.getpid()
    if _cache.pid == pid and _cache.instruments is not None:
        return _cache.instruments

    meter = bootstrap.get_meter()
    if meter is None:
        return None

    try:
        built = _Instruments(meter)
    except Exception:
        logger.exception("Could not create metric instruments; metrics are disabled")
        return None

    _cache.instruments = built
    _cache.pid = pid
    return built


def reset_for_testing() -> None:
    """Drop the cached instrument set so a test can install a fresh provider."""
    _cache.instruments = None
    _cache.pid = None


def _mirror_to_sentry(key: str, attributes: dict) -> None:
    if not sentry_mirror_enabled():
        return
    try:
        import sentry_sdk  # noqa: PLC0415

        sentry_sdk.metrics.count(key, 1, attributes=attributes)
    except Exception:
        logger.debug("Could not mirror %s to Sentry metrics", key, exc_info=True)


def record_erddap_request(
    server,
    dataset,
    duration_s: float | None,
    outcome: str,
    rows: int | None = None,
) -> None:
    """Record one ERDDAP fetch: its duration, row count and outcome."""
    inst = instruments()
    if inst is None:
        return

    try:
        safe_outcome = _bounded(outcome, ERDDAP_OUTCOMES)
        server_name = str(server)

        # Server-only on the histograms; dataset would multiply by the bucket count.
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
        }
        inst.erddap_outcome.add(1, attributes)
        if safe_outcome != "success":
            _mirror_to_sentry("buoybarn.erddap.outcome", attributes)
    except Exception:
        logger.debug("Failed to record ERDDAP metrics", exc_info=True)


#: When an exception escapes an :func:`erddap_request` block and the caller has not named
#: an outcome, classify it by exception class name. Keyed on the name rather than the class
#: so this module stays independent of ``deployments`` -- ``BackoffError`` in particular is
#: raised by the error handlers themselves, deep inside the ``with`` body.
_OUTCOME_BY_EXCEPTION = {
    "BackoffError": "backoff",
    "TimeoutException": "timeout",
    "ConnectError": "timeout",
    "ConnectTimeout": "timeout",
    "ReadTimeout": "timeout",
    "OSError": "os_error",
}


class OutcomeTracker:
    """Mutable outcome holder handed out by :func:`erddap_request`."""

    def __init__(self) -> None:
        self.outcome = "success"
        self.rows: int | None = None

    def set(self, outcome: str, rows: int | None = None) -> None:
        self.outcome = outcome
        if rows is not None:
            self.rows = rows


@contextmanager
def erddap_request(server, dataset):
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
        # An exception escaping the block means the fetch did not succeed, even if nothing
        # set an outcome -- most importantly BackoffError, which the 408/429 handlers raise
        # from inside the caller's own `except HTTPError` branch.
        if tracker.outcome == "success":
            tracker.set(_OUTCOME_BY_EXCEPTION.get(type(exc).__name__, "unknown_error"))
        raise
    finally:
        record_erddap_request(
            server,
            dataset,
            time.monotonic() - started,
            tracker.outcome,
            tracker.rows,
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

    Worth counting because every ping call site swallows ``requests.RequestException``: a
    monitor that silently stops being pinged would otherwise look identical to a healthy
    one right up until the monitor itself alerts.
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

    This is the backstop for the pipeline's swallowed errors: ``handle_http_errors`` and
    friends log and return rather than raising, so Celery reports success even when every
    fetch failed. Counting records needs no call-site changes and cannot disturb the log
    text that the test suite asserts on.
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
