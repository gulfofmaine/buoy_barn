"""Shared pytest fixtures.

The repo's first conftest -- the suite previously relied entirely on Django TestCase
classes and per-module fixtures.
"""

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource

# Safe to import at module scope even though conftest loads before django.setup():
# bootstrap and metrics only touch the standard library at import time, and pull Django in
# lazily inside the functions that need it.
from buoy_barn.observability import bootstrap, metrics


@pytest.fixture
def metric_reader():
    """Collect metrics in memory instead of shipping them to a collector.

    Installs a real ``MeterProvider`` backed by an ``InMemoryMetricReader``, so tests
    exercise the actual SDK -- instrument creation, attribute handling, aggregation -- with
    no network and no exporter thread. Yields a helper whose ``points(name)`` returns the
    data points for one metric.

    Metrics are off during tests by default (``settings.py`` disables the layer when
    ``DJANGO_ENV=test``), so a test that wants to assert on them must ask for this fixture.
    """
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        resource=Resource.create({"service.name": "buoy-barn-tests"}),
        metric_readers=[reader],
    )
    bootstrap.reset_for_testing(provider)
    metrics.reset_for_testing()

    yield MetricCollector(reader)

    bootstrap.reset_for_testing(None)
    metrics.reset_for_testing()
    provider.shutdown()


class MetricCollector:
    """Thin read helper over an ``InMemoryMetricReader``."""

    def __init__(self, reader) -> None:
        self.reader = reader

    def collected(self) -> dict[str, list]:
        """All data points recorded so far, keyed by metric name."""
        data = self.reader.get_metrics_data()
        if data is None:
            return {}
        return {
            metric.name: list(metric.data.data_points)
            for resource_metric in data.resource_metrics
            for scope_metric in resource_metric.scope_metrics
            for metric in scope_metric.metrics
        }

    def points(self, name: str) -> list:
        """Data points for one metric, or [] if it has not been recorded."""
        return self.collected().get(name, [])

    def counts(self, name: str, *attributes: str) -> dict:
        """Map the given attribute values to the recorded value, for assertions.

        With one attribute the key is that value; with several it is a tuple.
        """
        result = {}
        for point in self.points(name):
            key = tuple(point.attributes.get(attribute) for attribute in attributes)
            result[key[0] if len(key) == 1 else key] = point.value
        return result
