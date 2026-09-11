from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.test import TransactionTestCase
from django.utils import timezone
from freezegun import freeze_time
from requests import Response
from requests.exceptions import HTTPError

from buoy_barn.observability import metrics, promql
from deployments import tasks
from deployments.models import (
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    SystemMessage,
    TimeSeries,
)
from deployments.tasks.error_handling import BackoffError
from deployments.utils.system_messages import record_system_message

from .vcr import CASSETTE_RECORDED_AT, my_vcr


def _http_status_error(status_code: int, text: str) -> HTTPError:
    """Build an `HTTPError` shaped the way `handle_http_errors` expects to unwrap it.

    `handle_http_errors` reads `error.__cause__.response`, which is how erddapy's real
    errors are chained -- so tests that need a specific ERDDAP response body construct one
    directly instead of recording a new VCR cassette for it.
    """
    response = Response()
    response.status_code = status_code
    response._content = text.encode()
    status_error = HTTPError(f"{status_code} error", response=response)
    error = HTTPError(str(status_error))
    error.__cause__ = status_error
    return error


@pytest.mark.django_db
class TaskTestCase(TransactionTestCase):
    # Django DB Fixtures
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap",
        )

        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")
        self.water_temp = DataType.objects.get(standard_name="sea_water_temperature")
        self.current_direction = DataType.objects.get(
            standard_name="direction_of_sea_water_velocity",
        )

        self.ds_M01_sbe37 = ErddapDataset.objects.create(
            name="M01_sbe37_all",
            server=self.erddap,
        )

        # two time series from the same dataset and constraints
        self.ts1 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.salinity,
            variable="salinity",
            constraints={"depth=": 100.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            dataset=self.ds_M01_sbe37,
        )
        self.ts2 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable="temperature",
            constraints={"depth=": 100.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            dataset=self.ds_M01_sbe37,
        )

        # one with the same dataset but a different constraint
        self.ts3 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable="temperature",
            constraints={"depth=": 1.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            dataset=self.ds_M01_sbe37,
        )

        self.ds_M01_aanderaa = ErddapDataset.objects.create(
            name="M01_aanderaa_all",
            server=self.erddap,
        )

        # one with a different dataset
        self.ts4 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.current_direction,
            variable="current_direction",
            constraints={"depth=": 2.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            dataset=self.ds_M01_aanderaa,
        )

        # one that has an end_time so it should not be offered
        self.ts5 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable="temperature",
            constraints={"depth=": 100.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            end_time="2007-06-03 21:00:00+00",
            dataset=self.ds_M01_sbe37,
        )

    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_server(self, update_values_for_timeseries):
        tasks.refresh_server(self.erddap.id)

        self.assertEqual(
            3,
            update_values_for_timeseries.call_count,
            (
                "The server should have three distinct dataset/constraint "
                "groups of timeseries to be called with"
            ),
        )

    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_dataset(self, update_values_for_timeseries):
        tasks.refresh_dataset(self.ds_M01_sbe37.id)

        self.assertEqual(
            2,
            update_values_for_timeseries.call_count,
            "The dataset should have two groups of timeseries that have different constraints",
        )

    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_dataset_with_clear_end_time_includes_retired_series(
        self,
        update_values_for_timeseries,
    ):
        """`clear_end_time=True` is how `erddap_mqtt` recovers a wrongly-retired series

        (issue #1855) -- so `ts5`, which is excluded by `test_refresh_dataset` above, must be
        offered back to `update_values_for_timeseries` when a caller actually asks for that.
        """
        tasks.refresh_dataset(self.ds_M01_sbe37.id, clear_end_time=True)

        # Still two constraint groups (depth=100 and depth=1) -- ts5 joins ts1/ts2's group
        # rather than getting one of its own.
        self.assertEqual(
            2,
            update_values_for_timeseries.call_count,
            "ts5 should join its constraint group's call, not start a new one",
        )

        groups_seen = [call.args[0] for call in update_values_for_timeseries.call_args_list]
        matching_group = next(
            (group for group in groups_seen if self.ts5 in group),
            None,
        )
        self.assertIsNotNone(matching_group, "ts5 should be included when clear_end_time=True")
        self.assertIn(self.ts1, matching_group)
        self.assertIn(self.ts2, matching_group)

    @my_vcr.use_cassette("tasks_update_values.yaml")
    def test_update_values(self):
        self.assertIsNone(self.ts1.value)
        self.assertIsNone(self.ts2.value)

        tasks.update_values_for_timeseries((self.ts1, self.ts2))

        self.assertIsNotNone(self.ts1.value)
        self.assertIsNotNone(self.ts2.value)

    @my_vcr.use_cassette("tasks_update_values.yaml")
    def test_update_values_resolves_a_previous_fetch_failure(self):
        group = metrics.constraint_group_id(self.ts1.constraints)
        record_system_message(
            self.ds_M01_sbe37,
            SystemMessage.Code.NOT_FOUND,
            "previously not found",
            level=SystemMessage.Level.DANGER,
            constraint_group=group,
        )

        tasks.update_values_for_timeseries((self.ts1, self.ts2))

        message = SystemMessage.objects.for_object(self.ds_M01_sbe37).get(
            code=SystemMessage.Code.NOT_FOUND,
        )
        self.assertIsNotNone(message.resolved_at)

    @my_vcr.use_cassette("tasks_update_values.yaml")
    def test_update_values_resolves_a_previous_backoff_increase(self):
        group = metrics.constraint_group_id(self.ts1.constraints)
        record_system_message(
            self.ds_M01_sbe37,
            SystemMessage.Code.BACKOFF_INCREASED,
            "previously backing off",
            level=SystemMessage.Level.WARNING,
            constraint_group=group,
        )

        tasks.update_values_for_timeseries((self.ts1, self.ts2))

        message = SystemMessage.objects.for_object(self.ds_M01_sbe37).get(
            code=SystemMessage.Code.BACKOFF_INCREASED,
        )
        self.assertIsNotNone(message.resolved_at)

    @patch("deployments.tasks.refresh.retrieve_dataframe")
    def test_time_range_reported_records_an_info_message_without_retiring(
        self,
        retrieve_dataframe,
    ):
        recent_end = timezone.now() - timedelta(days=2)
        compare_text = (
            "Your query produced no matching results. (time&gt;=2020-10-04T19:40:20Z is "
            "outside of the variable's actual_range: 2018-07-17T17:00:00Z to "
            f"{recent_end.strftime('%Y-%m-%dT%H:%M:%SZ')})"
        )
        retrieve_dataframe.side_effect = _http_status_error(500, compare_text)

        tasks.update_values_for_timeseries([self.ts1])

        message = SystemMessage.objects.for_object(self.ds_M01_sbe37).get(
            code=SystemMessage.Code.TIME_RANGE_REPORTED,
        )
        self.assertEqual(message.level, SystemMessage.Level.INFO)

        self.ts1.refresh_from_db()
        self.assertIsNone(self.ts1.end_time)
        self.assertFalse(
            SystemMessage.objects.filter(code=SystemMessage.Code.END_TIME_RETIRED).exists(),
        )

    @my_vcr.use_cassette("tasks_update_values.yaml")
    def test_update_values_clears_end_time_and_resolves_retirement(self):
        self.ts1.end_time = datetime(2020, 1, 1, tzinfo=dt_timezone.utc)
        self.ts1.save()

        SystemMessage.objects.create(
            timeseries=self.ts1,
            code=SystemMessage.Code.END_TIME_RETIRED,
            level=SystemMessage.Level.DANGER,
            message="Retired earlier",
        )

        tasks.update_values_for_timeseries((self.ts1, self.ts2), clear_end_time=True)

        self.ts1.refresh_from_db()
        self.assertIsNone(self.ts1.end_time)

        cleared = SystemMessage.objects.for_object(self.ts1).get(
            code=SystemMessage.Code.END_TIME_CLEARED,
        )
        self.assertEqual(cleared.level, SystemMessage.Level.INFO)

        retired = SystemMessage.objects.for_object(self.ts1).get(
            code=SystemMessage.Code.END_TIME_RETIRED,
        )
        self.assertIsNotNone(retired.resolved_at)

    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_dataset_records_backoff_increase(self, update_values_for_timeseries):
        update_values_for_timeseries.side_effect = BackoffError("timeout")

        tasks.refresh_dataset(self.ds_M01_sbe37.id)

        # ds_M01_sbe37 has two constraint groups, both timing out under the mock -- one row
        # per group, not a single row merged across the whole dataset.
        messages = SystemMessage.objects.for_object(self.ds_M01_sbe37).filter(
            code=SystemMessage.Code.BACKOFF_INCREASED,
        )
        self.assertEqual(messages.count(), 2)
        for message in messages:
            self.assertEqual(message.level, SystemMessage.Level.WARNING)
            self.assertIn("previous_request_refresh_time_seconds", message.context)
            self.assertIn("new_request_refresh_time_seconds", message.context)

    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_dataset_records_backoff_with_the_failing_constraint_group(
        self,
        update_values_for_timeseries,
    ):
        update_values_for_timeseries.side_effect = BackoffError("timeout")

        # A dataset with a single constraint group, so the recorded message is unambiguous.
        tasks.refresh_dataset(self.ds_M01_aanderaa.id)

        expected_group = metrics.constraint_group_id(self.ts4.constraints)
        message = SystemMessage.objects.for_object(self.ds_M01_aanderaa).get(
            code=SystemMessage.Code.BACKOFF_INCREASED,
        )
        self.assertEqual(message.constraint_group, expected_group)

    @patch("requests.get")
    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_dataset_records_a_soft_time_limit(self, update_values_for_timeseries, get):
        """A soft timeout used to vanish: nothing caught it, so nothing said the run stopped."""
        update_values_for_timeseries.side_effect = SoftTimeLimitExceeded()
        self.ds_M01_sbe37.healthcheck_url = "https://hc.example/dataset"
        self.ds_M01_sbe37.save()

        # Re-raised, so Celery still marks the task failed and the postrun signal records it.
        with self.assertRaises(SoftTimeLimitExceeded):
            tasks.refresh_dataset(self.ds_M01_sbe37.id, healthcheck=True)

        message = SystemMessage.objects.for_object(self.ds_M01_sbe37).get(
            code=SystemMessage.Code.TASK_SOFT_TIME_LIMIT,
        )
        self.assertEqual(message.level, SystemMessage.Level.DANGER)
        self.assertEqual(message.context["processed"], 0)
        self.assertEqual(message.context["total"], 2, "sbe37 has two refreshable constraint groups")
        self.assertIn("soft_time_limit_seconds", message.context)

        # `/fail` and never the bare completion URL: a run that timed out did not complete,
        # and pinging both would leave the monitor looking healthy.
        self.assertEqual(
            [call.args[0] for call in get.call_args_list],
            ["https://hc.example/dataset/start", "https://hc.example/dataset/fail"],
        )

    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_dataset_resolves_a_previous_soft_time_limit(self, update_values_for_timeseries):
        record_system_message(
            self.ds_M01_sbe37,
            SystemMessage.Code.TASK_SOFT_TIME_LIMIT,
            "previously timed out",
            level=SystemMessage.Level.DANGER,
        )

        tasks.refresh_dataset(self.ds_M01_sbe37.id)

        message = SystemMessage.objects.for_object(self.ds_M01_sbe37).get(
            code=SystemMessage.Code.TASK_SOFT_TIME_LIMIT,
        )
        self.assertIsNotNone(message.resolved_at)

    @patch("requests.get")
    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_server_records_a_soft_time_limit(self, update_values_for_timeseries, get):
        update_values_for_timeseries.side_effect = SoftTimeLimitExceeded()
        self.erddap.healthcheck_url = "https://hc.example/server"
        self.erddap.save()

        with self.assertRaises(SoftTimeLimitExceeded):
            tasks.refresh_server(self.erddap.id, healthcheck=True)

        message = SystemMessage.objects.for_object(self.erddap).get(
            code=SystemMessage.Code.TASK_SOFT_TIME_LIMIT,
        )
        self.assertEqual(message.level, SystemMessage.Level.DANGER)
        self.assertEqual(message.context["processed"], 0)
        self.assertEqual(message.context["total"], 2, "the server has two datasets to refresh")

        # The nested `refresh_dataset` call records its own dataset-scoped message on the way
        # past, so an operator can see which dataset the run was stuck on. Which dataset that
        # is depends on iteration order, so only the existence of one is asserted here.
        self.assertTrue(
            SystemMessage.objects.filter(
                code=SystemMessage.Code.TASK_SOFT_TIME_LIMIT,
                dataset__isnull=False,
            ).exists(),
        )

        # Only the server's own monitor is pinged: the nested call is not the healthcheck one.
        self.assertEqual(
            [call.args[0] for call in get.call_args_list],
            ["https://hc.example/server/start", "https://hc.example/server/fail"],
        )

    @patch("deployments.tasks.refresh.update_values_for_timeseries")
    def test_refresh_server_resolves_a_previous_soft_time_limit(self, update_values_for_timeseries):
        record_system_message(
            self.erddap,
            SystemMessage.Code.TASK_SOFT_TIME_LIMIT,
            "previously timed out",
            level=SystemMessage.Level.DANGER,
        )

        tasks.refresh_server(self.erddap.id)

        message = SystemMessage.objects.for_object(self.erddap).get(
            code=SystemMessage.Code.TASK_SOFT_TIME_LIMIT,
        )
        self.assertIsNotNone(message.resolved_at)

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    @patch("deployments.tasks.refresh.task_queued")
    def test_single_refresh_dataset_skips_when_queued(self, task_queued, refresh_dataset_delay):
        task_queued.return_value = True

        tasks.single_refresh_dataset(self.ds_M01_sbe37.id)

        refresh_dataset_delay.assert_not_called()

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    @patch("deployments.tasks.refresh.task_queued")
    def test_single_refresh_dataset_enqueues_when_not_queued(self, task_queued, refresh_dataset_delay):
        task_queued.return_value = False

        tasks.single_refresh_dataset(self.ds_M01_sbe37.id, healthcheck=True, clear_end_time=True)

        refresh_dataset_delay.assert_called_once_with(
            self.ds_M01_sbe37.id,
            healthcheck=True,
            clear_end_time=True,
        )

        self.assertEqual(
            task_queued.call_args[0][0],
            tasks.refresh_dataset.name,
            "task_queued should be called with the actual registered task name",
        )

    @patch("deployments.tasks.refresh.refresh_server.delay")
    @patch("deployments.tasks.refresh.task_queued")
    def test_single_refresh_server_skips_when_queued(self, task_queued, refresh_server_delay):
        task_queued.return_value = True

        tasks.single_refresh_server(self.erddap.id)

        refresh_server_delay.assert_not_called()

    @patch("deployments.tasks.refresh.refresh_server.delay")
    @patch("deployments.tasks.refresh.task_queued")
    def test_single_refresh_server_enqueues_when_not_queued(self, task_queued, refresh_server_delay):
        task_queued.return_value = False

        tasks.single_refresh_server(self.erddap.id, healthcheck=True)

        refresh_server_delay.assert_called_once_with(self.erddap.id, healthcheck=True)

        self.assertEqual(
            task_queued.call_args[0][0],
            tasks.refresh_server.name,
            "task_queued should be called with the actual registered task name",
        )
        self.assertEqual(task_queued.call_args[0][1], [self.erddap.id])


@pytest.mark.django_db
@freeze_time(CASSETTE_RECORDED_AT)
class TaskErrorTestCase(TransactionTestCase):
    """Replay the recorded ERDDAP failures.

    Frozen because the request URL `setup_variables` builds embeds `datetime.now(UTC)`:
    without a fixed clock every run asks the cassettes for a different time range, and
    the tests drift away from what was recorded.
    """

    # Django DB Fixtures
    fixtures = ["platforms", "erddapservers", "datatypes"]

    # Py.test fixtures
    @pytest.fixture(autouse=True)
    def __inject_fixtures(self, caplog):
        self.caplog = caplog

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap",
        )

        self.ds = ErddapDataset.objects.create(
            name="N01_accelerometer_all",
            server=self.erddap,
        )
        self.ts = TimeSeries.objects.create(
            platform=self.platform,
            data_type=DataType.objects.get(standard_name="sea_water_velocity"),
            variable="current_speed",
            constraints={},
            start_time="2004-06-03 21:00:00+00",
            dataset=self.ds,
        )

    @my_vcr.use_cassette("500.yaml")
    def test_500_unrecognized_variable(self):
        dataset = ErddapDataset.objects.get(name="N01_accelerometer_all")

        tasks.refresh_dataset(dataset.id)

        assert "Unrecognized variable for dataset" in self.caplog.text

    @my_vcr.use_cassette("500_end_time.yaml")
    def test_500_end_time(self):
        j03 = Platform.objects.get(name="J03")
        dataset = ErddapDataset.objects.create(
            name="J03_aanderaa_all",
            server=self.erddap,
        )
        ts = TimeSeries.objects.create(
            platform=j03,
            data_type=DataType.objects.get(standard_name="sea_water_salinity"),
            variable="salinity",
            constraints={},
            start_time="2018-07-17 17:00:00+00",
            dataset=dataset,
        )

        ts.refresh_from_db()

        assert ts.end_time is None

        tasks.update_values_for_timeseries([ts])

        ts.refresh_from_db()

        assert ts.end_time is not None
        assert "Set end time for" in self.caplog.text

    @my_vcr.use_cassette("500_no_rows.yaml")
    def test_500_no_rows(self):
        a01 = Platform.objects.get(name="A01")
        dataset = ErddapDataset.objects.create(name="A01_sbe37_all", server=self.erddap)
        ts = TimeSeries.objects.create(
            platform=a01,
            data_type=DataType.objects.get(standard_name="sea_water_salinity"),
            variable="salinity",
            constraints={"depth=": 1.0, "salinity_qc=": 0},
            start_time="2001-07-10T04:00:01Z",
            dataset=dataset,
        )

        ts.refresh_from_db()

        assert ts.value is None

        tasks.update_values_for_timeseries([ts])

        ts.refresh_from_db()

        assert ts.value is None

        # assert "did not return any results" in self.caplog.text

        # `no_rows` is benign -- the one outcome the observability docs call out as such --
        # so it must never turn into a SystemMessage, or every quiet dataset would start
        # looking like a standing failure in the admin.
        assert SystemMessage.objects.count() == 0

    @my_vcr.use_cassette("500_no_rows.yaml")
    def test_500_no_rows_resolves_a_previous_fetch_failure(self):
        """A benign outcome must still close out a stale failure for the same group.

        `no_rows` never gets its own row in `FETCH_FAILURE_MESSAGES` (it's benign), which
        used to mean the `if handled: return` early exit skipped resolution entirely for it
        -- leaving a stale DANGER outstanding forever even once the dataset started
        answering quietly instead of failing.
        """
        a01 = Platform.objects.get(name="A01")
        dataset = ErddapDataset.objects.create(name="A01_sbe37_all", server=self.erddap)
        ts = TimeSeries.objects.create(
            platform=a01,
            data_type=DataType.objects.get(standard_name="sea_water_salinity"),
            variable="salinity",
            constraints={"depth=": 1.0, "salinity_qc=": 0},
            start_time="2001-07-10T04:00:01Z",
            dataset=dataset,
        )
        group = metrics.constraint_group_id(ts.constraints)
        record_system_message(
            dataset,
            SystemMessage.Code.FORBIDDEN,
            "previously forbidden",
            level=SystemMessage.Level.DANGER,
            constraint_group=group,
        )

        tasks.update_values_for_timeseries([ts])

        message = SystemMessage.objects.for_object(dataset).get(
            code=SystemMessage.Code.FORBIDDEN,
        )
        self.assertIsNotNone(message.resolved_at)

    @my_vcr.use_cassette("404_no_matching_dataset")
    def test_switching_failure_mode_resolves_the_stale_message(self):
        """A dataset that switches failure mode must not keep the old message forever.

        A stale `forbidden` DANGER, recorded on a previous run, must be resolved once this
        run records `not_found` instead -- and the freshly recorded `not_found` must *not*
        be immediately resolved along with it.
        """
        wlis = Platform.objects.get(name="WLIS")
        dataset = ErddapDataset.objects.create(
            name="UCONN_WLIS_MET",
            server=self.erddap,
        )
        ts = TimeSeries.objects.create(
            platform=wlis,
            data_type=DataType.objects.get(standard_name="wind_from_direction"),
            variable="wind_direction",
            constraints={},
            start_time="2019-12-30T12:00:00",
            dataset=dataset,
        )
        group = metrics.constraint_group_id(ts.constraints)
        record_system_message(
            dataset,
            SystemMessage.Code.FORBIDDEN,
            "previously forbidden",
            level=SystemMessage.Level.DANGER,
            constraint_group=group,
        )

        tasks.update_values_for_timeseries([ts])

        forbidden = SystemMessage.objects.for_object(dataset).get(
            code=SystemMessage.Code.FORBIDDEN,
        )
        self.assertIsNotNone(forbidden.resolved_at)

        not_found = SystemMessage.objects.for_object(dataset).get(
            code=SystemMessage.Code.NOT_FOUND,
        )
        self.assertIsNone(not_found.resolved_at)

    @my_vcr.use_cassette("500_no_rows_actual_range.yaml")
    def test_500_actual_range(self):
        a01 = Platform.objects.get(name="A01")
        dataset = ErddapDataset.objects.create(
            name="A01_waves_mstrain_all",
            server=self.erddap,
        )
        ts = TimeSeries.objects.create(
            platform=a01,
            data_type=DataType.objects.get(standard_name="max_wave_height"),
            variable="maximum_wave_height_3",
            constraints={"maximum_wave_height_3_qc=": 0},
            start_time="2019-05-29T19:06:07",
            dataset=dataset,
        )

        ts.refresh_from_db()

        assert ts.value is None

        tasks.update_values_for_timeseries([ts])

        ts.refresh_from_db()

        assert ts.value is None
        assert "Unable to parse datetimes in error processing dataset" in self.caplog.text

    @my_vcr.use_cassette("500_unrecognized_constraint.yaml")
    def test_500_unrecognized_contraint(self):
        e01 = Platform.objects.get(name="E01")
        dataset = ErddapDataset.objects.create(
            name="E01_aanderaa_all",
            server=self.erddap,
        )
        ts = TimeSeries.objects.create(
            platform=e01,
            data_type=DataType.objects.get(
                standard_name="direction_of_sea_water_velocity",
            ),
            variable="current_direction",
            constraints={"direction_of_sea_water_velocity_qc=": 0},
            start_time="2001-07-09T12:00:00",
            dataset=dataset,
        )

        ts.refresh_from_db()

        assert ts.value is None

        tasks.update_values_for_timeseries([ts])

        ts.refresh_from_db()

        assert ts.value is None
        assert "Invalid constraint variable for dataset" in self.caplog.text

    @my_vcr.use_cassette("404_no_matching_dataset")
    def test_404_no_matching_dataset(self):
        wlis = Platform.objects.get(name="WLIS")
        dataset = ErddapDataset.objects.create(
            name="UCONN_WLIS_MET",
            server=self.erddap,
        )
        ts = TimeSeries.objects.create(
            platform=wlis,
            data_type=DataType.objects.get(standard_name="wind_from_direction"),
            variable="wind_direction",
            constraints={},
            start_time="2019-12-30T12:00:00",
            dataset=dataset,
        )

        ts.refresh_from_db()

        assert ts.value is None

        tasks.update_values_for_timeseries([ts])

        ts.refresh_from_db()

        assert ts.value is None
        assert "is currently unknown by the server" in self.caplog.text

        message = SystemMessage.objects.for_object(dataset).get(
            code=SystemMessage.Code.NOT_FOUND,
        )
        assert message.level == SystemMessage.Level.DANGER
        assert message.constraint_group == metrics.constraint_group_id(ts.constraints)

        # The emitter's `context` and `promql.query_for`'s required keys are two halves of one
        # contract that nothing else checks: drop "dataset" from the context above and every
        # test still passes while the admin quietly stops offering a query. Assert the whole
        # round trip rather than the presence of a key.
        query = promql.query_for(
            message.code,
            {**message.context, "constraint_group": message.constraint_group},
        )
        assert query is not None
        assert dataset.name in query

    @my_vcr.use_cassette("400_unrecognized_variable")
    def test_400_unrecognized_variable(self):
        # platform = Platform.objects.create(name="44076")
        server = ErddapServer.objects.create(
            name="OOI",
            base_url="http://erddap.dataexplorer.oceanobservatories.org/erddap",
        )
        dataset = ErddapDataset.objects.create(
            name="ooi-cp03issm-sbd11-06-metbka000",
            server=server,
        )
        ts = TimeSeries.objects.create(
            platform=self.platform,
            data_type=DataType.objects.get(
                standard_name="sea_surface_swell_wave_period",
            ),
            variable="sea_surface_wave_significant_period",
            constraints={},
            start_time="2019-01-01T00:00:00",
            dataset=dataset,
        )

        ts.refresh_from_db()

        assert ts.value is None

        tasks.update_values_for_timeseries([ts])

        ts.refresh_from_db()

        assert ts.value is None
        assert "Unrecognized variable for dataset" in self.caplog.text

    @my_vcr.use_cassette("404_no_matching_station")
    def test_404_no_matching_station(self):
        # platform = Platform.objects.get(name="BLTM3")
        server = ErddapServer.objects.create(
            name="Coastwatch",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap",
        )
        dataset = ErddapDataset.objects.create(name="nosCoopsMW", server=server)
        ts = TimeSeries.objects.create(
            platform=self.platform,
            data_type=DataType.objects.get(standard_name="wind_from_direction"),
            variable="WD",
            constraints={"stationID=": "8447387 "},
            start_time="2019-01-01T00:00:00",
            dataset=dataset,
        )
        ts.refresh_from_db()

        assert ts.value is None

        tasks.update_values_for_timeseries([ts])

        ts.refresh_from_db()

        assert ts.value is None
        assert "does not have a requested station. Please check the constraints" in self.caplog.text

    # @my_vcr.use_cassette("404_no_data_matches_time")
    # def test_404_no_data_matches_time(self):
    #     # platform = Platform.objects.create(name="44077")
    #     server = ErddapServer.objects.create(
    #         name="OOI",
    #         base_url="http://erddap.dataexplorer.oceanobservatories.org/erddap",
    #     )
    #     dataset = ErddapDataset.objects.create(
    #         name="ooi-cp04ossm-sbd11-06-metbka000", server=server
    #     )
    #     ts = TimeSeries.objects.create(
    #         platform=self.platform,
    #         data_type=DataType.objects.get(standard_name="air_temperature"),
    #         variable="air_temperature",
    #         constraints={},
    #         start_time="2016-09-16T00:00:00",
    #         dataset=dataset,
    #     )

    #     ts.refresh_from_db()

    #     assert ts.value is None

    #     tasks.update_values_for_timeseries([ts])

    #     ts.refresh_from_db()

    #     assert ts.value is None
    #     assert "Unrecognized variable for dataset" in self.caplog.text
