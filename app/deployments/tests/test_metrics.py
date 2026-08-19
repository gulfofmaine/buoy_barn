"""Tests for the observability layer.

The headline test is `test_failed_refresh_records_a_failure_outcome`: it proves the gap this
instrumentation exists to close. The refresh pipeline swallows ERDDAP errors, so the Celery
task reports success even when the fetch failed -- these tests assert that the outcome
counter tells the truth anyway.

Metrics are disabled during the suite (settings.py switches the layer off when
DJANGO_ENV=test), so any test asserting on metrics takes the `metric_reader` fixture, which
installs a real SDK provider backed by an in-memory reader.
"""

import hashlib
import logging
import re
import time
from unittest.mock import patch

import pytest
import requests
from django.test import TransactionTestCase
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from buoy_barn.observability import bootstrap, celery_signals, freshness, metrics
from buoy_barn.observability.log_metrics import MetricsLogHandler
from deployments import tasks
from deployments.models import (
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    TimeSeries,
)
from deployments.tasks.error_handling import BackoffError
from deployments.utils.healthchecks import ping_healthcheck

from .vcr import my_vcr

ERDDAP_OUTCOME = "buoybarn.erddap.outcome"
ERDDAP_DURATION = "buoybarn.erddap.request.duration"
ERDDAP_ROWS = "buoybarn.erddap.request.rows"

#: Arbitrary but fixed values, named so the comparisons below read as intent.
ROW_COUNT = 12
EXPECTED_OK_PINGS = 2
SIMULATED_QUEUE_WAIT_SECONDS = 5
MINIMUM_OBSERVED_WAIT_SECONDS = 4.5
EXPECTED_GAUGE_COUNT = 6


class TestDisabledLayer:
    """With no provider configured the whole layer must be inert, not merely quiet."""

    def test_recording_functions_are_noops(self):
        bootstrap.reset_for_testing(None)
        metrics.reset_for_testing()

        assert metrics.instruments() is None

        # None of these may raise, and none may configure an exporter.
        metrics.record_erddap_request("server", "dataset", 1.0, "timeout", rows=0)
        metrics.record_task("task", "success", 2.0)
        metrics.record_task_queue_latency("task", 3.0)
        metrics.task_in_progress("task", 1)
        metrics.record_healthcheck_ping("monitor", "error")
        metrics.record_log("logger", "error")
        with metrics.erddap_request("server", "dataset") as outcome:
            outcome.set("no_rows", rows=0)

        assert bootstrap._state.provider is None

    def test_enabled_follows_the_endpoint(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
        monkeypatch.setenv("DJANGO_ENV", "dev")
        assert bootstrap.enabled() is False

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        assert bootstrap.enabled() is True

        # DJANGO_ENV=test always wins, so the suite never starts an exporter.
        monkeypatch.setenv("DJANGO_ENV", "test")
        assert bootstrap.enabled() is False


class TestRole:
    def test_explicit_role_wins(self, monkeypatch):
        monkeypatch.setenv("BUOY_BARN_OTEL_ROLE", "beat")
        assert bootstrap.guess_role() == "beat"

    def test_unknown_role_is_not_passed_through(self, monkeypatch):
        """An unrecognised role must not become a new resource attribute value."""
        monkeypatch.setenv("BUOY_BARN_OTEL_ROLE", "something-else")
        assert bootstrap.guess_role() == "unknown"

    def test_role_guessed_from_argv(self, monkeypatch):
        monkeypatch.delenv("BUOY_BARN_OTEL_ROLE", raising=False)
        monkeypatch.setattr("sys.argv", ["celery", "-A", "buoy_barn", "worker", "-l", "info"])
        assert bootstrap.guess_role() == "worker"

        monkeypatch.setattr("sys.argv", ["manage.py", "export_metrics"])
        assert bootstrap.guess_role() == "exporter"


class TestCardinalityGuards:
    """Attribute values must stay inside their declared sets."""

    def test_unknown_outcome_collapses_to_other(self, metric_reader):
        metrics.record_erddap_request("neracoos", "A01_all", 1.0, "some ERDDAP error text")

        outcomes = metric_reader.counts(ERDDAP_OUTCOME, "outcome")
        assert "other" in outcomes
        assert "some ERDDAP error text" not in outcomes

    def test_dataset_is_not_an_attribute_on_histograms(self, metric_reader):
        """~384 datasets times a bucket count would be tens of thousands of series."""
        metrics.record_erddap_request("neracoos", "A01_all", 1.0, "success", rows=5)

        for name in (ERDDAP_DURATION, ERDDAP_ROWS):
            for point in metric_reader.points(name):
                assert "erddap.dataset" not in point.attributes

        # The counter is where per-dataset detail belongs.
        assert any(
            "erddap.dataset" in point.attributes for point in metric_reader.points(ERDDAP_OUTCOME)
        )

    def test_unknown_celery_state_collapses_to_other(self, metric_reader):
        metrics.record_task("deployments.tasks.refresh.refresh_dataset", "PENDING-ish")

        states = metric_reader.counts("buoybarn.celery.task.count", "celery.state")
        assert "other" in states


class TestErddapRequestContextManager:
    def test_records_duration_and_rows(self, metric_reader):
        with metrics.erddap_request("neracoos", "A01_all") as outcome:
            outcome.set("success", rows=ROW_COUNT)

        assert metric_reader.counts(ERDDAP_OUTCOME, "outcome") == {"success": 1}
        rows = metric_reader.points(ERDDAP_ROWS)
        assert len(rows) == 1
        assert rows[0].sum == ROW_COUNT
        assert metric_reader.points(ERDDAP_DURATION)[0].count == 1

    def test_zero_rows_is_recorded(self, metric_reader):
        """A 200 response with an empty body is the failure mode row counts exist to catch."""
        with metrics.erddap_request("neracoos", "A01_all") as outcome:
            outcome.set("empty_dataframe", rows=0)

        assert metric_reader.points(ERDDAP_ROWS)[0].count == 1
        assert metric_reader.counts(ERDDAP_OUTCOME, "outcome") == {"empty_dataframe": 1}

    def test_escaping_exception_is_classified_and_reraised(self, metric_reader):
        """BackoffError is raised by the handlers themselves, inside the `with` body."""
        with pytest.raises(BackoffError), metrics.erddap_request("neracoos", "A01_all"):
            raise BackoffError("slow down")

        assert metric_reader.counts(ERDDAP_OUTCOME, "outcome") == {"backoff": 1}

    def test_unrecognised_exception_becomes_unknown_error(self, metric_reader):
        with pytest.raises(RuntimeError), metrics.erddap_request("neracoos", "A01_all"):
            raise RuntimeError("surprise")

        assert metric_reader.counts(ERDDAP_OUTCOME, "outcome") == {"unknown_error": 1}

    def test_explicit_outcome_is_not_overwritten_by_an_exception(self, metric_reader):
        with (
            pytest.raises(BackoffError),
            metrics.erddap_request("neracoos", "A01_all") as outcome,
        ):
            outcome.set("timeout")
            raise BackoffError("slow down")

        assert metric_reader.counts(ERDDAP_OUTCOME, "outcome") == {"timeout": 1}


class TestLogMetrics:
    def test_counts_records_by_logger_and_level(self, metric_reader):
        handler = MetricsLogHandler(level=logging.WARNING)
        log = logging.getLogger("deployments.tests.metrics-probe")
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
        try:
            log.info("chatty per-timeseries line")
            log.warning("something odd")
            log.error("a swallowed erddap failure")
        finally:
            log.removeHandler(handler)

        levels = metric_reader.counts("buoybarn.log.records", "level")
        # INFO is below the handler threshold set in settings; the tasks emit one per group.
        assert levels == {"warning": 1, "error": 1}

    def test_message_is_never_an_attribute(self, metric_reader):
        metrics.record_log("deployments.tasks.refresh", "error")

        for point in metric_reader.points("buoybarn.log.records"):
            assert set(point.attributes) == {"logger", "level"}


class TestHealthcheckPing:
    def test_unconfigured_monitor_is_silent(self, metric_reader):
        assert ping_healthcheck(None, "unconfigured") is False
        assert ping_healthcheck("", "unconfigured") is False
        assert metric_reader.points("buoybarn.healthcheck.ping") == []

    def test_successful_ping_hits_the_right_url(self, metric_reader):
        with patch("requests.get") as get:
            assert ping_healthcheck("https://hc.example/token", "hourly_refresh", start=True)
            assert ping_healthcheck("https://hc.example/token", "hourly_refresh")

        assert [call.args[0] for call in get.call_args_list] == [
            "https://hc.example/token/start",
            "https://hc.example/token",
        ]
        pings = metric_reader.counts("buoybarn.healthcheck.ping", "monitor", "outcome")
        assert pings[("hourly_refresh", "ok")] == EXPECTED_OK_PINGS

    def test_failed_ping_is_counted_and_swallowed(self, metric_reader):
        with patch("requests.get", side_effect=requests.ConnectionError("boom")):
            # Must not raise: a monitoring side channel cannot be allowed to fail a refresh.
            assert ping_healthcheck("https://hc.example/token", "hourly_refresh") is False

        pings = metric_reader.counts("buoybarn.healthcheck.ping", "monitor", "outcome")
        assert pings[("hourly_refresh", "error")] == 1


class TestFreshnessHelpers:
    def test_callback_failure_becomes_no_data(self):
        """An exception escaping a gauge callback can stop collection for the provider."""

        def boom():
            raise RuntimeError("the database went away")

        assert freshness._observations(boom) == []

    def test_null_labels_do_not_become_the_string_none(self):
        # ErddapServer.name is nullable.
        assert freshness._label(None) == "unknown"
        assert freshness._label("") == "unknown"
        assert freshness._label("neracoos") == "neracoos"

    def test_every_gauge_is_registered(self):
        reader = InMemoryMetricReader()
        provider = MeterProvider(metric_readers=[reader])
        gauges = freshness.register(provider.get_meter("test"))
        try:
            assert len(gauges) == len(freshness.GAUGES)
            assert "buoybarn.dataset.refresh_age" in freshness.GAUGES
            assert "buoybarn.timeseries.value_age" in freshness.GAUGES
            assert "buoybarn.celery.queue.depth" in freshness.GAUGES
        finally:
            provider.shutdown()


class TestCeleryTaskSignals:
    """The receivers are called directly: no broker, and no dependence on eager mode."""

    def _fake_task(self, name, published_at=None):
        class Request(dict):
            def get(self, key, default=None):
                return dict.get(self, key, default)

        request = Request()
        if published_at is not None:
            request["buoybarn_published_at"] = published_at

        class Task:
            pass

        task = Task()
        task.name = name
        task.request = request
        return task

    def test_prerun_and_postrun_balance_and_record_duration(self, metric_reader):
        name = "deployments.tasks.refresh.refresh_dataset"
        task = self._fake_task(name)

        celery_signals._on_task_prerun(task_id="abc", task=task, sender=None)
        celery_signals._on_task_postrun(task_id="abc", task=task, sender=None, state="SUCCESS")

        states = metric_reader.counts("buoybarn.celery.task.count", "celery.state")
        assert states == {"started": 1, "success": 1}
        assert metric_reader.points("buoybarn.celery.task.duration")[0].count == 1
        # Balanced back to zero, so the gauge shows genuinely stuck tasks.
        assert sum(p.value for p in metric_reader.points("buoybarn.celery.task.in_progress")) == 0
        # And the start-time map is drained rather than leaking an entry per task.
        assert "abc" not in celery_signals._start_times

    def test_queue_latency_from_the_publish_stamp(self, metric_reader):
        task = self._fake_task(
            "deployments.tasks.refresh.refresh_dataset",
            time.time() - SIMULATED_QUEUE_WAIT_SECONDS,
        )
        celery_signals._on_task_prerun(task_id="def", task=task, sender=None)
        celery_signals._on_task_postrun(
            task_id="def",
            task=task,
            sender=None,
            state="SUCCESS",
        )

        latency = metric_reader.points("buoybarn.celery.task.queue_latency")
        assert len(latency) == 1
        assert latency[0].sum >= MINIMUM_OBSERVED_WAIT_SECONDS

    def test_missing_publish_stamp_records_no_latency(self, metric_reader):
        task = self._fake_task("deployments.tasks.refresh.refresh_dataset")
        celery_signals._on_task_prerun(task_id="ghi", task=task, sender=None)

        # Better to have no data point than a fabricated zero.
        assert metric_reader.points("buoybarn.celery.task.queue_latency") == []

    def test_publish_stamp_is_added_to_headers(self):
        headers = {}
        celery_signals._stamp_publish_time(headers=headers)
        assert celery_signals.PUBLISHED_AT_HEADER in headers

        # No headers to stamp (older protocol / unusual call) must not raise.
        celery_signals._stamp_publish_time(headers=None)


@pytest.mark.django_db
class ErddapOutcomeMetricTestCase(TransactionTestCase):
    """Replay recorded ERDDAP failures and assert the outcome counter tells the truth.

    Mirrors `TaskErrorTestCase` in test_tasks.py, including its fixtures and cassettes. The
    expected outcome for each cassette is pinned by the log assertion the existing test
    makes: only one handler emits each of those messages, and each handler maps to one
    outcome.
    """

    fixtures = ["platforms", "erddapservers", "datatypes"]

    @pytest.fixture(autouse=True)
    def __inject_fixtures(self, caplog, metric_reader):
        self.caplog = caplog
        self.metrics = metric_reader

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap = ErddapServer.objects.get(base_url="http://www.neracoos.org/erddap")

    def _timeseries(self, platform_name, dataset_name, standard_name, variable, **kwargs):
        dataset = ErddapDataset.objects.create(name=dataset_name, server=self.erddap)
        return TimeSeries.objects.create(
            platform=Platform.objects.get(name=platform_name),
            data_type=DataType.objects.get(standard_name=standard_name),
            variable=variable,
            constraints=kwargs.pop("constraints", {}),
            start_time=kwargs.pop("start_time", "2019-01-01T00:00:00Z"),
            dataset=dataset,
        )

    def assert_outcome(self, expected):
        outcomes = self.metrics.counts(ERDDAP_OUTCOME, "outcome")
        assert outcomes == {expected: 1}, f"expected {expected!r}, recorded {outcomes!r}"
        # Duration is recorded for failures too, so a slow-failing server is visible.
        assert self.metrics.points(ERDDAP_DURATION)[0].count == 1

    @my_vcr.use_cassette("500.yaml")
    def test_unrecognized_variable_outcome(self):
        dataset = ErddapDataset.objects.create(
            name="N01_accelerometer_all",
            server=self.erddap,
        )
        TimeSeries.objects.create(
            platform=Platform.objects.get(name="M01"),
            data_type=DataType.objects.get(standard_name="sea_water_velocity"),
            variable="current_speed",
            constraints={},
            start_time="2004-06-03 21:00:00+00",
            dataset=dataset,
        )

        tasks.refresh_dataset(dataset.id)

        assert "Unrecognized variable for dataset" in self.caplog.text
        self.assert_outcome("unrecognized_variable")

    @my_vcr.use_cassette("500_end_time.yaml")
    def test_time_range_retired_outcome(self):
        timeseries = self._timeseries(
            "J03",
            "J03_aanderaa_all",
            "sea_water_salinity",
            "salinity",
            start_time="2018-07-17 17:00:00+00",
        )

        tasks.update_values_for_timeseries([timeseries])

        assert "Set end time for" in self.caplog.text
        self.assert_outcome("time_range_retired")

    @my_vcr.use_cassette("500_unrecognized_constraint.yaml")
    def test_unrecognized_constraint_outcome(self):
        timeseries = self._timeseries(
            "E01",
            "E01_aanderaa_all",
            "direction_of_sea_water_velocity",
            "current_direction",
            constraints={"direction_of_sea_water_velocity_qc=": 0},
            start_time="2001-07-09T12:00:00",
        )

        tasks.update_values_for_timeseries([timeseries])

        assert "Invalid constraint variable for dataset" in self.caplog.text
        self.assert_outcome("unrecognized_constraint")

    @my_vcr.use_cassette("404_no_matching_dataset")
    def test_not_found_outcome(self):
        timeseries = self._timeseries(
            "WLIS",
            "UCONN_WLIS_MET",
            "wind_from_direction",
            "wind_direction",
            start_time="2019-12-30T12:00:00",
        )

        tasks.update_values_for_timeseries([timeseries])

        assert "is currently unknown by the server" in self.caplog.text
        self.assert_outcome("not_found")

    @my_vcr.use_cassette("500_no_rows.yaml")
    def test_a_failed_refresh_never_records_success(self):
        """The cassette's exact handler is not pinned by a log assertion, so assert the
        invariant instead: a failed fetch must not be recorded as a success, and whatever
        outcome is recorded must come from the declared vocabulary."""
        timeseries = self._timeseries(
            "A01",
            "A01_sbe37_all",
            "sea_water_salinity",
            "salinity",
            constraints={"depth=": 1.0, "salinity_qc=": 0},
            start_time="2001-07-10T04:00:01Z",
        )

        tasks.update_values_for_timeseries([timeseries])

        timeseries.refresh_from_db()
        assert timeseries.value is None

        outcomes = self.metrics.counts(ERDDAP_OUTCOME, "outcome")
        assert "success" not in outcomes, outcomes
        assert set(outcomes) <= metrics.ERDDAP_OUTCOMES, outcomes

    @my_vcr.use_cassette("500.yaml")
    def test_task_succeeds_while_the_outcome_records_failure(self):
        """The reason this instrumentation exists.

        `refresh_dataset` swallows ERDDAP errors, so Celery sees success and a task-level
        failure counter would read zero. The outcome counter is what makes the failure
        visible.
        """
        dataset = ErddapDataset.objects.create(
            name="N01_accelerometer_all",
            server=self.erddap,
        )
        TimeSeries.objects.create(
            platform=Platform.objects.get(name="M01"),
            data_type=DataType.objects.get(standard_name="sea_water_velocity"),
            variable="current_speed",
            constraints={},
            start_time="2004-06-03 21:00:00+00",
            dataset=dataset,
        )

        # No exception: from Celery's point of view this refresh succeeded.
        tasks.refresh_dataset(dataset.id)

        outcomes = self.metrics.counts(ERDDAP_OUTCOME, "outcome")
        assert outcomes and "success" not in outcomes, outcomes

        # And the swallowed error was also counted as a log record.
        assert self.metrics.counts("buoybarn.log.records", "level").get("error", 0) >= 1


class TestConstraintGroupId:
    """A dataset is fetched per (constraints, type) group, so the id is what makes one
    failing group distinguishable from its healthy siblings."""

    def test_empty_constraints_are_readable(self):
        """Most datasets have no constraints; "none" beats the hash of an empty dict."""
        assert metrics.constraint_group_id(None) == metrics.NO_CONSTRAINTS
        assert metrics.constraint_group_id({}) == metrics.NO_CONSTRAINTS

    def test_stable_and_order_independent(self):
        """Same constraints built in a different order must not become two groups."""
        first = metrics.constraint_group_id({"depth=": 1.0, "salinity_qc=": 0})
        second = metrics.constraint_group_id({"salinity_qc=": 0, "depth=": 1.0})

        assert first == second
        assert first == metrics.constraint_group_id({"depth=": 1.0, "salinity_qc=": 0})

    def test_distinct_constraints_are_distinct_ids(self):
        assert metrics.constraint_group_id({"stationID=": "8447387"}) != metrics.constraint_group_id(
            {"depth=": 1.0},
        )

    def test_id_shape(self):
        assert re.fullmatch(r"[0-9a-f]{8}", metrics.constraint_group_id({"depth=": 1.0}))

    def test_shape_validation_rejects_free_text(self):
        """The value is a hash, so it cannot be checked against a frozenset like the other
        attributes -- its shape is validated instead, keeping free text off labels."""
        assert metrics._bounded_group_id("a1b2c3d4") == "a1b2c3d4"
        assert metrics._bounded_group_id(None) == metrics.NO_CONSTRAINTS

        for rejected in ('{"depth=": 1.0}', "NOTAHASH", "a1b2c3d", "A1B2C3D4", "a1b2c3d4e"):
            assert metrics._bounded_group_id(rejected) == metrics.OTHER, rejected


class TestConstraintGroupLabels:
    def test_group_labels_are_on_the_counter_only(self, metric_reader):
        """On a histogram they would multiply by the bucket count."""
        group = metrics.constraint_group_id({"depth=": 1.0})

        with metrics.erddap_request(
            "neracoos",
            "A01_all",
            constraint_group=group,
            timeseries_type="Observation",
        ) as outcome:
            outcome.set("not_found", rows=0)

        for point in metric_reader.points(ERDDAP_OUTCOME):
            assert point.attributes["constraint_group"] == group
            assert point.attributes["timeseries.type"] == "Observation"

        for name in (ERDDAP_DURATION, ERDDAP_ROWS):
            for point in metric_reader.points(name):
                assert "constraint_group" not in point.attributes
                assert "timeseries.type" not in point.attributes

    def test_labels_are_always_present(self, metric_reader):
        """A query should never have to cope with the metric existing both with and without
        these labels, so an unsupplied value still emits one."""
        metrics.record_erddap_request("neracoos", "A01_all", 1.0, "success", rows=3)

        point = metric_reader.points(ERDDAP_OUTCOME)[0]
        assert point.attributes["constraint_group"] == metrics.NO_CONSTRAINTS
        assert point.attributes["timeseries.type"] == "unknown"

    def test_unknown_timeseries_type_collapses(self, metric_reader):
        metrics.record_erddap_request(
            "neracoos",
            "A01_all",
            1.0,
            "success",
            timeseries_type="NotAChoice",
        )

        assert metric_reader.points(ERDDAP_OUTCOME)[0].attributes["timeseries.type"] == metrics.OTHER


class TestConstraintGroupInfo:
    """The counter's group id is opaque, so the exporter publishes a lookup metric. If the two
    sides ever disagree the Grafana join silently returns nothing."""

    def test_exporter_label_is_the_canonical_form_the_id_hashes(self):
        """Assert the relationship directly rather than trusting that both call one helper."""
        for constraints in ({"depth=": 1.0, "salinity_qc=": 0}, {"stationID=": "8447387 "}):
            group_id = metrics.constraint_group_id(constraints)
            label = freshness._constraints_label(constraints)

            assert label == metrics.canonical_constraints(constraints)
            assert hashlib.sha256(label.encode("utf-8")).hexdigest()[:8] == group_id

    def test_empty_constraints_agree_on_both_sides(self):
        assert freshness._constraints_label({}) == metrics.NO_CONSTRAINTS
        assert metrics.constraint_group_id({}) == metrics.NO_CONSTRAINTS

    def test_absurd_constraints_are_truncated_without_affecting_the_id(self):
        huge = {f"key{index}=": "x" * 20 for index in range(50)}

        label = freshness._constraints_label(huge)

        assert len(label) <= freshness.MAX_CONSTRAINTS_LABEL
        assert label.endswith("\u2026")
        # Truncation is presentational only; the id still hashes the full constraints.
        assert re.fullmatch(r"[0-9a-f]{8}", metrics.constraint_group_id(huge))

    def test_info_gauge_is_registered(self):
        assert "buoybarn.erddap.constraint_group.info" in freshness.GAUGES
        assert len(freshness.GAUGES) == EXPECTED_GAUGE_COUNT
