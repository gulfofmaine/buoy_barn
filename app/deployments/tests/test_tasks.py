from unittest.mock import patch

import pytest

from django.test import TransactionTestCase

from deployments import tasks
from deployments.models import (
    Platform,
    ErddapDataset,
    ErddapServer,
    DataType,
    TimeSeries,
)
from .vcr import my_vcr


@pytest.mark.django_db
class TaskTestCase(TransactionTestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap"
        )

        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")
        self.water_temp = DataType.objects.get(standard_name="sea_water_temperature")
        self.current_direction = DataType.objects.get(
            standard_name="direction_of_sea_water_velocity"
        )

        self.ds_M01_sbe37 = ErddapDataset.objects.create(
            name="M01_sbe37_all", server=self.erddap
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
            name="M01_aanderaa_all", server=self.erddap
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

    @patch("deployments.tasks.update_values_for_timeseries")
    def test_refresh_server(self, update_values_for_timeseries):
        tasks.refresh_server(self.erddap.id)

        self.assertEqual(
            3,
            update_values_for_timeseries.call_count,
            "The server should have three distinct dataset/constraint groups of timeseries to be called with",
        )

    @patch("deployments.tasks.update_values_for_timeseries")
    def test_refresh_dataset(self, update_values_for_timeseries):
        tasks.refresh_dataset(self.ds_M01_sbe37.id)

        self.assertEqual(
            2,
            update_values_for_timeseries.call_count,
            "The dataset should have two groups of timeseries that have different constraints",
        )

    @my_vcr.use_cassette("tasks_update_values.yaml")
    def test_update_values(self):
        self.assertIsNone(self.ts1.value)
        self.assertIsNone(self.ts2.value)

        tasks.update_values_for_timeseries((self.ts1, self.ts2))

        self.assertIsNotNone(self.ts1.value)
        self.assertIsNotNone(self.ts2.value)


@pytest.mark.django_db
class TaskErrorTestCase(TransactionTestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap"
        )

        self.ds = ErddapDataset.objects.create(
            name="N01_accelerometer_all", server=self.erddap
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
    def test_500_response_doesnt_explode(self):
        dataset = ErddapDataset.objects.get(name="N01_accelerometer_all")

        tasks.refresh_dataset(dataset.id)

    @my_vcr.use_cassette("500_end_time.yaml")
    def test_500_end_time(self):
        j03 = Platform.objects.get(name="J03")
        dataset = ErddapDataset.objects.create(
            name="J03_aanderaa_all", server=self.erddap
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
