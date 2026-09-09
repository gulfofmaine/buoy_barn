"""Ping a Healthchecks.io monitor.

This consolidates the behaviour and adds a metric, so a monitor that silently stops
being pinged is visible instead of looking identical to a healthy one.

The log messages are kept in the same shape as the originals on purpose: they are the only
record of a failed ping in the existing deployment, so anything grepping for them keeps
working.
"""

import logging

from buoy_barn.observability import metrics

logger = logging.getLogger(__name__)


def ping_healthcheck(url: str | None, monitor: str, *, start: bool = False, fail: bool = False) -> bool:
    """Ping a Healthchecks.io monitor. Returns True if the ping was accepted.

    Args:
        url: Base monitor URL. A falsy value means the monitor is not configured, which is
            normal -- most datasets have none -- so nothing happens and nothing is counted.
        monitor: Short label used as the metric attribute. Must be low cardinality, so pass
            something like a dataset or task name, never a full URL.
        start: Ping the ``/start`` endpoint instead of the completion endpoint.
        fail: Ping the ``/fail`` endpoint, which records the run as failed immediately
            instead of leaving the monitor to notice once its grace period lapses.

    Raises ``ValueError`` if both ``start`` and ``fail`` are given: that is a bug at the call
    site rather than a runtime condition, so it should be loud. Nothing that happens on the
    network raises -- a monitoring side channel must not be able to fail a refresh.
    """
    if start and fail:
        raise ValueError("ping_healthcheck takes start or fail, not both")

    if not url:
        return False

    import requests  # noqa: PLC0415

    if start:
        target = url + "/start"
    elif fail:
        target = url + "/fail"
    else:
        target = url

    try:
        requests.get(target, timeout=5)
    except requests.RequestException as error:
        if start:
            message = f"Unable to send healthcheck start for {monitor} due to: {error}"
        elif fail:
            message = f"Unable to send healthcheck failure for {monitor} due to error: {error}"
        else:
            message = f"Unable to send healthcheck completion for {monitor} due to error: {error}"
        logger.error(message, exc_info=True)
        metrics.record_healthcheck_ping(monitor, "error")
        return False

    metrics.record_healthcheck_ping(monitor, "ok")
    return True
