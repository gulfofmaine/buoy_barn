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


def ping_healthcheck(url: str | None, monitor: str, *, start: bool = False) -> bool:
    """Ping a Healthchecks.io monitor. Returns True if the ping was accepted.

    Args:
        url: Base monitor URL. A falsy value means the monitor is not configured, which is
            normal -- most datasets have none -- so nothing happens and nothing is counted.
        monitor: Short label used as the metric attribute. Must be low cardinality, so pass
            something like a dataset or task name, never a full URL.
        start: Ping the ``/start`` endpoint instead of the completion endpoint.

    Never raises: a monitoring side channel must not be able to fail a refresh.
    """
    if not url:
        return False

    import requests  # noqa: PLC0415

    target = url + "/start" if start else url
    try:
        requests.get(target, timeout=5)
    except requests.RequestException as error:
        message = (
            f"Unable to send healthcheck start for {monitor} due to: {error}"
            if start
            else f"Unable to send healthcheck completion for {monitor} due to error: {error}"
        )
        logger.error(message, exc_info=True)
        metrics.record_healthcheck_ping(monitor, "error")
        return False

    metrics.record_healthcheck_ping(monitor, "ok")
    return True
