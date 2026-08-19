"""Celery task metrics, wired entirely through signals.

No task function is edited: everything here hangs off Celery's own signals, so adding a
task automatically gets it measured.

Two things are load-bearing about *where* this runs:

* ``worker_process_init`` is the only correct place to configure the SDK in a prefork
  worker. See :mod:`buoy_barn.observability.bootstrap` for why configuring in the parent
  silently discards every metric.
* ``before_task_publish`` fires in the **producer** -- the web process, beat, or the MQTT
  command -- not in the worker. That is why ``buoy_barn.celery`` imports this module
  rather than the worker importing it: every process that publishes a task needs the
  receiver installed, or queue latency goes unmeasured.

Task counting deliberately uses ``task_postrun``'s ``state`` rather than ``task_failure``.
``task_postrun`` fires for success, failure *and* retry, so counting in both places would
double-count every failure.
"""

import logging
import time

from celery.signals import (
    beat_init,
    before_task_publish,
    task_postrun,
    task_prerun,
    task_revoked,
    worker_process_init,
    worker_process_shutdown,
)

from . import bootstrap, metrics

logger = logging.getLogger(__name__)

#: Message header carrying the publish timestamp used to derive queue latency.
PUBLISHED_AT_HEADER = "buoybarn_published_at"

#: Wall-clock start times, keyed by task id, populated in prerun and drained in postrun.
#: Wall clock rather than a monotonic clock because publish and execution happen in
#: different processes, where monotonic values are not comparable.
_start_times: dict[str, float] = {}


def _task_name(task, sender) -> str:
    for candidate in (getattr(task, "name", None), getattr(sender, "name", None), sender):
        if candidate:
            return str(candidate)
    return "unknown"


@worker_process_init.connect
def _init_worker_process(**_kwargs) -> None:
    """Build this prefork child's MeterProvider.

    Must happen here: exporter threads do not survive the fork from the worker parent.
    """
    bootstrap.configure(role="worker")


@worker_process_shutdown.connect
def _shutdown_worker_process(**_kwargs) -> None:
    """Flush before the child exits, or up to one export interval is lost with it."""
    bootstrap.shutdown()


@beat_init.connect
def _init_beat(**_kwargs) -> None:
    bootstrap.configure(role="beat")


@before_task_publish.connect
def _stamp_publish_time(headers=None, **_kwargs) -> None:
    """Record when a task was published so the worker can measure its queue wait."""
    if headers is None:
        return
    try:
        headers[PUBLISHED_AT_HEADER] = time.time()
    except Exception:
        logger.debug("Could not stamp publish time on task headers", exc_info=True)


def _queue_latency(task) -> float | None:
    """Seconds a task spent waiting to run, or None if the publish stamp is missing."""
    request = getattr(task, "request", None)
    if request is None:
        return None

    try:
        published_at = request.get(PUBLISHED_AT_HEADER)
    except AttributeError:
        published_at = getattr(request, PUBLISHED_AT_HEADER, None)

    if not published_at:
        return None
    try:
        # Clamped at zero: publisher and worker are different pods, so a little clock
        # skew is expected and a negative wait is meaningless.
        return max(time.time() - float(published_at), 0.0)
    except (TypeError, ValueError):
        return None


@task_prerun.connect
def _on_task_prerun(task_id=None, task=None, sender=None, **_kwargs) -> None:
    name = _task_name(task, sender)
    if task_id:
        _start_times[task_id] = time.time()

    metrics.record_task(name, "started")
    metrics.task_in_progress(name, 1)

    latency = _queue_latency(task)
    if latency is not None:
        metrics.record_task_queue_latency(name, latency)


@task_postrun.connect
def _on_task_postrun(task_id=None, task=None, sender=None, state=None, **_kwargs) -> None:
    name = _task_name(task, sender)
    started = _start_times.pop(task_id, None) if task_id else None
    duration = time.time() - started if started is not None else None

    metrics.record_task(name, str(state or "").lower(), duration_s=duration)
    metrics.task_in_progress(name, -1)


@task_revoked.connect
def _on_task_revoked(sender=None, request=None, **_kwargs) -> None:
    """Count revocations.

    A task revoked mid-execution also fires ``task_postrun``, so it can be counted twice.
    Revocation is rare enough here (nothing in the codebase calls ``revoke``) that the
    duplicate is worth less than losing the signal entirely.
    """
    name = str(getattr(request, "name", None) or getattr(sender, "name", None) or "unknown")
    metrics.record_task(name, "revoked")
