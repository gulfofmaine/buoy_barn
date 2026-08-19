"""Long-running process that exports database-derived metrics.

Run as its own single-replica deployment. See buoy_barn.observability.freshness for why
these gauges are collected here rather than from the workers.
"""

import logging
import signal
import threading

from django.core.management.base import BaseCommand

from buoy_barn.observability import bootstrap, freshness

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Export data-freshness and queue-depth metrics over OTLP until terminated"

    def handle(self, *args, **options):
        if not bootstrap.configure(role="exporter"):
            # Not an error: the same image runs everywhere, and a deployment without an
            # OTLP endpoint configured should idle quietly rather than crash-loop.
            logger.warning(
                "OTEL_EXPORTER_OTLP_ENDPOINT is not set, so there is nothing to export. "
                "Exiting; see buoy_barn.observability.bootstrap for the configuration.",
            )
            return

        meter = bootstrap.get_meter()
        # Held for the process lifetime: if these are garbage collected, collection stops.
        gauges = freshness.register(meter)
        logger.info("Exporting %d gauges; waiting for termination", len(gauges))

        stop = threading.Event()

        def _stop(signum, _frame):
            logger.info("Received signal %s; shutting down the metrics exporter", signum)
            stop.set()

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        # The SDK's PeriodicExportingMetricReader does the collecting on its own thread;
        # this process only has to stay alive and then flush cleanly on the way out.
        stop.wait()
        bootstrap.shutdown()
        logger.info("Metrics exporter stopped")
