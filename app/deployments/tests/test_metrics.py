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
import threading
import time
from datetime import timedelta
from unittest.mock import patch

import pytest
import requests
from django.test import TransactionTestCase
from django.utils import timezone
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from buoy_barn.observability import bootstrap, celery_signals, freshness, metrics
from buoy_barn.observability.log_metrics import MetricsLogHandler
from deployments import tasks
from deployments.management.commands.export_metrics import Command as ExportMetricsCommand
from deployments.models import (
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    TimeSeries,
)
from deployments.tasks import error_handling
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

#: Ages the freshness tests set up, in seconds, with a generous allowance for how long the
#: test itself takes between building the rows and reading the gauge.
ONE_HOUR_SECONDS = 3600
TWO_HOURS_SECONDS = 7200
SIX_HOURS_SECONDS = 21600
LEEWAY_SECONDS = 60

#: The outcomes a dashboard may safely ignore. Every other outcome corresponds to a handler
#: that logs at ERROR -- see the outcome table in docs/observability.md.
BENIGN_OUTCOMES = {"success", "no_rows"}

#: Two distinct constraint groups are set up by the grouping tests below.
EXPECTED_GROUP_COUNT = 2


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

    def test_granian_is_web_despite_its_workers_flag(self, monkeypatch):
        """The real Dockerfile CMD. `--workers 4` used to match the "worker" hint first."""
        monkeypatch.delenv("BUOY_BARN_OTEL_ROLE", raising=False)
        monkeypatch.setattr(
            "sys.argv",
            [
                "granian",
                "--interface",
                "asgi",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "--workers",
                "4",
                "buoy_barn.asgi:application",
            ],
        )
        assert bootstrap.guess_role() == "web"

    def test_celery_subcommands_are_only_matched_for_celery(self, monkeypatch):
        monkeypatch.delenv("BUOY_BARN_OTEL_ROLE", raising=False)
        for argv, expected in (
            (["celery", "-A", "buoy_barn", "beat", "-l", "info"], "beat"),
            (["celery", "-A", "buoy_barn", "flower", "-l", "info"], "flower"),
            (["manage.py", "export_metrics"], "exporter"),
            (["manage.py", "erddap_mqtt", "NERACOOS_SEA_EAGLE"], "mqtt"),
            # Not Celery and not a server: a bare subcommand word must not match.
            (["some-tool", "--beat-detection"], "unknown"),
        ):
            monkeypatch.setattr("sys.argv", argv)
            assert bootstrap.guess_role() == expected, argv

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


@pytest.mark.django_db
class FreshnessGaugeTestCase(TransactionTestCase):
    """Run every freshness callback against a real database.

    This is the class that should have existed from the start. The original harness asserted
    only that collection *survived* an unreachable database by reporting no data -- and under
    that assertion a query that is simply broken is indistinguishable from a dead database.
    `_timeseries_counts` was broken from the first commit (an annotation alias shadowed
    `TimeSeries.active`, so Postgres rejected the nested aggregate), `_observations` swallowed
    it, and the gauge silently published nothing.

    So the rule for these tests: assert on **non-empty** observations with real values. An
    empty list is the failure mode, never a pass.
    """

    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.now = timezone.now()
        self.platform = Platform.objects.get(name="M01")
        self.data_type = DataType.objects.get(standard_name="sea_water_temperature")
        self.server = ErddapServer.objects.get(base_url="http://www.neracoos.org/erddap")
        self.dataset = ErddapDataset.objects.create(
            name="M01_sbe37_all",
            server=self.server,
            refresh_attempted=self.now - timedelta(hours=2),
        )

    def _timeseries(self, **kwargs):
        return TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.data_type,
            variable=kwargs.pop("variable", "temperature"),
            dataset=kwargs.pop("dataset", self.dataset),
            start_time=self.now - timedelta(days=30),
            **kwargs,
        )

    def test_dataset_refresh_ages_are_real_seconds(self):
        observations = freshness._observations(freshness._dataset_refresh_ages)

        assert len(observations) == 1
        observation = observations[0]
        assert observation.attributes["erddap.dataset"] == "M01_sbe37_all"
        # Two hours ago, give or take the time this test takes to run.
        assert TWO_HOURS_SECONDS <= observation.value < TWO_HOURS_SECONDS + LEEWAY_SECONDS

    def test_datasets_never_refreshed_are_counted(self):
        ErddapDataset.objects.create(name="never_run", server=self.server)

        observations = freshness._observations(freshness._datasets_never_refreshed)

        assert [observation.value for observation in observations] == [1]

    def test_value_ages_report_newest_and_oldest(self):
        self._timeseries(value_time=self.now - timedelta(hours=1), value=10.0)
        self._timeseries(
            variable="temperature2",
            value_time=self.now - timedelta(hours=6),
            value=11.0,
        )
        # Retired and inactive series must not drag the gauge.
        self._timeseries(
            variable="retired",
            value_time=self.now - timedelta(days=400),
            end_time=self.now,
        )
        self._timeseries(
            variable="inactive",
            value_time=self.now - timedelta(days=400),
            active=False,
        )

        observations = freshness._observations(freshness._timeseries_value_ages)

        by_agg = {observation.attributes["agg"]: observation.value for observation in observations}
        assert set(by_agg) == {"min", "max"}
        # agg=min is the *freshest* reading: one hour, not four hundred days.
        assert ONE_HOUR_SECONDS <= by_agg["min"] < ONE_HOUR_SECONDS + LEEWAY_SECONDS
        assert SIX_HOURS_SECONDS <= by_agg["max"] < SIX_HOURS_SECONDS + LEEWAY_SECONDS

    def test_timeseries_counts_publishes_every_state(self):
        """The regression test for the annotation-alias collision.

        Before the fix this callback raised `FieldError`/`ProgrammingError` every cycle and
        `_observations` turned that into an empty list, so the gauge never published at all.
        """
        self._timeseries(value_time=self.now, value=1.0)
        self._timeseries(variable="inactive", active=False, value_time=self.now, value=2.0)
        self._timeseries(variable="retired", end_time=self.now, value_time=self.now, value=3.0)
        self._timeseries(variable="fresh")  # never populated: no value_time

        observations = freshness._observations(freshness._timeseries_counts)

        assert observations, "the gauge published nothing at all"
        by_state = {observation.attributes["state"]: observation.value for observation in observations}
        assert by_state == {
            "active": 2,  # the populated one and the never-populated one
            "inactive": 1,
            "retired": 1,
            "never_populated": 1,
        }

    def test_constraint_group_info_describes_each_group(self):
        self._timeseries(constraints={"depth=": 1.0}, value_time=self.now, value=1.0)
        self._timeseries(
            variable="temperature2",
            constraints={"depth=": 50.0},
            value_time=self.now,
            value=2.0,
        )

        observations = freshness._observations(freshness._constraint_group_info)

        assert len(observations) == EXPECTED_GROUP_COUNT
        assert {observation.value for observation in observations} == {1}
        assert {observation.attributes["constraints"] for observation in observations} == {
            '{"depth=":1.0}',
            '{"depth=":50.0}',
        }

    def test_group_ids_match_what_the_refresh_path_records(self):
        """The Grafana join is silent when the two sides disagree, so assert them equal.

        `group_timeseries_by_constraint_and_type` decides what the refresh path fetches (and
        therefore what `record_erddap_request` labels); `_constraint_group_info` decides what
        the lookup metric describes. Both now filter through
        `TimeSeries.objects.refreshable()`, but a shared filter is not a proof -- the *key*
        could still drift.
        """
        self._timeseries(constraints={"depth=": 1.0}, value_time=self.now, value=1.0)
        self._timeseries(variable="temperature2", constraints={"depth=": 50.0})
        self._timeseries(variable="ignored", constraints={"depth=": 99.0}, active=False)

        from_model = {
            (self.dataset.name, metrics.constraint_group_id(dict(constraints)))
            for constraints, _type in self.dataset.group_timeseries_by_constraint_and_type()
        }
        from_exporter = {
            (observation.attributes["erddap.dataset"], observation.attributes["constraint_group"])
            for observation in freshness._observations(freshness._constraint_group_info)
        }

        assert from_model == from_exporter
        # The inactive series is in neither set.
        assert len(from_model) == EXPECTED_GROUP_COUNT, from_model

    def test_server_label_agrees_with_the_counter_for_a_nameless_server(self):
        """`ErddapServer.name` is nullable, and the two sides used to disagree about it.

        The counter labelled the server `str(server)` -- name or base URL -- while every gauge
        used the name alone, falling back to "unknown". So for a server without a name the
        `constraint_group.info` join returned nothing at all.
        """
        nameless = ErddapServer.objects.create(name=None, base_url="http://example.com/erddap")
        ErddapDataset.objects.create(
            name="nameless_dataset",
            server=nameless,
            refresh_attempted=self.now - timedelta(hours=1),
        )

        gauge_labels = {
            observation.attributes["erddap.server"]
            for observation in freshness._observations(freshness._dataset_refresh_ages)
        }

        assert metrics.server_label(nameless) in gauge_labels
        assert metrics.server_label(nameless) == "http://example.com/erddap"


class TestLoggingRecursion:
    """A setup failure must not recurse through the log handler that records log records.

    `MetricsLogHandler` sits on the root logger at WARNING, and both `bootstrap.configure`
    and `metrics.instruments` log when they fail. So a failure logs, the handler records the
    log, recording asks for a provider, and configuration is attempted again -- once per log
    record, until the stack runs out. Three guards break the loop; these tests assert the
    behaviour rather than the guards, so a future refactor cannot quietly reintroduce it.
    """

    def _install_handler(self):
        handler = MetricsLogHandler(level=logging.WARNING)
        root = logging.getLogger()
        root.addHandler(handler)
        return handler

    def test_a_failing_provider_build_does_not_recurse(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("DJANGO_ENV", "production")
        bootstrap.reset_for_testing(None)
        metrics.reset_for_testing()

        attempts = []

        def explode(role):
            attempts.append(role)
            # Exactly what the real failure does: log, then report no provider.
            logging.getLogger("buoy_barn.observability.bootstrap").exception("boom")

        monkeypatch.setattr(bootstrap, "_build_provider", explode)
        handler = self._install_handler()
        try:
            for _ in range(3):
                assert bootstrap.configure() is False
                logging.getLogger("deployments.tasks").warning("a later, unrelated warning")
        finally:
            logging.getLogger().removeHandler(handler)
            bootstrap.reset_for_testing(None)
            metrics.reset_for_testing()

        # One attempt in total: the failure is remembered, so neither the log record it
        # emitted nor any later one triggers another build.
        assert len(attempts) == 1, attempts

    def test_a_failing_instrument_build_does_not_recurse(self, monkeypatch):
        reader = InMemoryMetricReader()
        provider = MeterProvider(metric_readers=[reader])
        bootstrap.reset_for_testing(provider)
        metrics.reset_for_testing()

        attempts = []

        class Exploding:
            def __init__(self, meter):
                attempts.append(meter)
                raise RuntimeError("no instruments for you")

        monkeypatch.setattr(metrics, "_Instruments", Exploding)
        handler = self._install_handler()
        try:
            for _ in range(3):
                assert metrics.instruments() is None
                logging.getLogger("deployments.tasks").error("something failed")
        finally:
            logging.getLogger().removeHandler(handler)
            bootstrap.reset_for_testing(None)
            metrics.reset_for_testing()
            provider.shutdown()

        assert len(attempts) == 1, attempts

    def test_the_handler_refuses_to_re_enter_itself(self, monkeypatch):
        """The outermost guard, independent of what the layers below it do.

        On its own logger rather than the root one, because `settings.LOGGING` already
        attaches a handler there and a second handler counting the same record is correct
        behaviour, not recursion -- it would just obscure what this test is about.
        """
        isolated = logging.getLogger("buoy_barn.tests.recursion")
        isolated.propagate = False
        recorded = []

        def record_log_that_logs(logger_name, level):
            recorded.append(logger_name)
            # A future call site logging from inside record_log must not loop.
            isolated.warning("recording failed")

        monkeypatch.setattr(metrics, "record_log", record_log_that_logs)
        handler = MetricsLogHandler(level=logging.WARNING)
        isolated.addHandler(handler)
        try:
            isolated.warning("the original record")
        finally:
            isolated.removeHandler(handler)

        # The record emitted from inside `record_log` reaches the handler and is dropped.
        assert recorded == ["buoy_barn.tests.recursion"]


class TestExporterCommand:
    """`export_metrics` runs as a Deployment, so returning is a crash loop."""

    def test_it_waits_instead_of_exiting_when_disabled(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", raising=False)
        bootstrap.reset_for_testing(None)

        command = ExportMetricsCommand()
        stop = threading.Event()
        monkeypatch.setattr(command, "_stop_event", lambda: stop)

        finished = threading.Event()

        def run():
            command.handle()
            finished.set()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            # Returning immediately means the container exits 0 and gets restarted, which is
            # the crash loop the command exists to avoid.
            assert not finished.wait(timeout=0.5), "the command returned instead of idling"
            stop.set()
            assert finished.wait(timeout=5), "the command ignored its stop event"
        finally:
            stop.set()
            worker.join(timeout=5)


class TestOutcomeVocabulary:
    """The benign/actionable split is what dashboards alert on, so pin it."""

    def test_the_new_outcomes_are_declared(self):
        assert "constraint_out_of_range" in metrics.ERDDAP_OUTCOMES
        assert "no_matching_time" in metrics.ERDDAP_OUTCOMES

    def test_error_level_handlers_do_not_report_a_benign_outcome(self):
        """`no_rows` is benign, so an ERROR-level condition needs an outcome of its own.

        These two used to return `no_rows`, which any dashboard filtering on "not benign"
        would have hidden. The handlers are called with the real response text so the test
        breaks if a mapping is changed rather than merely if a constant is renamed.
        """
        cases = (
            (
                error_handling.handle_500_variable_actual_range_error,
                "Your query produced no matching results. "
                "(depth=1.0 is outside of the variable&#39;s actual_range: 50.0 to 100.0)",
                "constraint_out_of_range",
            ),
            (
                error_handling.handle_404_no_matching_time,
                "No data matches time>=2020-01-01 (code=404)",
                "no_matching_time",
            ),
            (
                error_handling.handle_500_no_rows_error,
                "Query error: nRows = 0",
                "no_rows",
            ),
        )

        group = [_FakeTimeSeries()]
        for handler, response_text, expected in cases:
            outcome = handler(group, response_text)
            assert outcome == expected, handler.__name__
            assert outcome in metrics.ERDDAP_OUTCOMES, handler.__name__
            # The rule under test: only the INFO-level handler may report a benign outcome.
            logs_at_info = handler is error_handling.handle_500_no_rows_error
            assert (outcome in BENIGN_OUTCOMES) is logs_at_info, handler.__name__


class _FakeTimeSeries:
    """Just enough of a TimeSeries for the handlers' log messages and `error_extra`.

    The handlers under test only read these attributes, so this keeps the vocabulary test
    out of the database.
    """

    class _Dataset:
        name = "M01_sbe37_all"
        server = "NERACOOS"

    constraints = {"depth=": 1.0}
    dataset = _Dataset()

    def __str__(self):
        return "fake timeseries"
