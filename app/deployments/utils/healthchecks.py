"""One place to ping a Healthchecks.io monitor.

The same start/complete ping was written four times -- twice on ``ErddapDataset``, twice on
``ErddapServer``, and inline in ``periodic_refresh`` -- each swallowing
``requests.RequestException`` with a slightly different log message. This consolidates the
behaviour and adds a metric, so a monitor that silently stops being pinged is visible
instead of looking identical to a healthy one.

The log messages are kept in the same shape as the originals on purpose: they are the only
record of a failed ping in the existing deployment, and some are asserted on in tests.
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
        # Wording preserved verbatim from the five call sites this replaced, including the
        # inconsistent "due to:" / "due to error:" split, so existing log greps still match.
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
