"""A logging handler that counts records as metrics.

This is the cheapest possible coverage of the pipeline's biggest blind spot. Almost every
ERDDAP failure is logged and swallowed rather than raised -- ``handle_http_errors`` returns
for every branch it recognises, ``OSError`` logs and returns, an empty dataframe is a
warning -- so Celery reports ~100% task success even when every fetch is failing.

Counting log records by logger and level covers all ~15 ``logger.error`` sites in
``deployments.tasks.error_handling`` and the rest in ``deployments.tasks.refresh`` without
touching a single call site, and without disturbing the log message text that the test
suite asserts on via ``caplog``.

Attributes are the logger name and the level only -- never the message, which would be
unbounded cardinality.
"""

import logging

from . import metrics


class MetricsLogHandler(logging.Handler):
    """Increment ``buoybarn.log.records`` for each record, by logger and level.

    Installed through Django's ``LOGGING`` setting, which attaches it at ``WARNING``: the
    tasks log an ``INFO`` line per timeseries group, and counting those would be high
    volume for very little signal. Warnings and errors are the interesting part.

    A no-op when metrics are switched off, and it swallows its own errors: a broken metrics
    pipeline must never break logging.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            metrics.record_log(record.name, record.levelname)
        except Exception:  # pragma: no cover - defensive; record_log already guards
            self.handleError(record)
