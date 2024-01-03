from unittest.mock import patch

import pytest
from django.test import TransactionTestCase

from deployments import tasks
from deployments.models import (
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    TimeSeries,
)

from .vcr import my_vcr


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

    @my_vcr.use_cassette("tasks_update_values.yaml")
    def test_update_values(self):
        self.assertIsNone(self.ts1.value)
        self.assertIsNone(self.ts2.value)

        tasks.update_values_for_timeseries((self.ts1, self.ts2))

        self.assertIsNotNone(self.ts1.value)
        self.assertIsNotNone(self.ts2.value)


@pytest.mark.django_db
class TaskErrorTestCase(TransactionTestCase):
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
        assert (
            "Unable to parse datetimes in error processing dataset" in self.caplog.text
        )

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
        assert (
            "does not have a requested station. Please check the constraints"
            in self.caplog.text
        )

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
