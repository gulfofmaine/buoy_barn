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
import threading

from . import metrics

#: "This thread is already recording a metric for a log record." Deliberately shared by every
#: handler instance rather than held per handler: whether we are inside a recording is a
#: property of the thread, not of one handler. Two handlers each guarding only themselves
#: would still bounce a record between them -- handler A records, that logs, handler B is
#: unguarded and records, which logs again. Thread-local rather than a plain global because
#: two threads logging at once are unrelated, and a shared flag would let one thread's
#: recording silently drop the other's record.
_recording = threading.local()


class MetricsLogHandler(logging.Handler):
    """Increment ``buoybarn.log.records`` for each record, by logger and level.

    Installed through Django's ``LOGGING`` setting, which attaches it at ``WARNING``: the
    tasks log an ``INFO`` line per timeseries group, and counting those would be high
    volume for very little signal. Warnings and errors are the interesting part.

    A no-op when metrics are switched off, and it swallows its own errors: a broken metrics
    pipeline must never break logging.

    Re-entrancy is guarded here as well as in the layers below, because this handler closes
    a loop the rest of the package cannot see: recording a metric can fail, a failure is
    logged, and the log record arrives back at this handler. `bootstrap.configure` and
    `metrics.instruments` both refuse to retry a failed build, which breaks that loop at
    the bottom -- but a handler that can cause logging must be safe on its own terms,
    whatever a future call site does inside `record_log`.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(_recording, "active", False):
            return
        _recording.active = True
        try:
            metrics.record_log(record.name, record.levelname)
        except Exception:  # pragma: no cover - defensive; record_log already guards
            self.handleError(record)
        finally:
            _recording.active = False
