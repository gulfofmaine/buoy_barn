from unittest.mock import patch

import geojson
import pytest
from rest_framework.test import APITestCase

from deployments.models import (
    BufferType,
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    TimeSeries,
)

from .vcr import my_vcr


@pytest.mark.django_db
class BuoyBarnPlatformAPITestCase(APITestCase):
    fixtures = ["platforms", "erddapservers"]

    def setUp(self):
        self.platform = Platform.objects.get(name="N01")
        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap",
        )

        # self.conductivity = DataType.objects.get(standard_name='sea_water_electrical_conductivity')
        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")
        self.water_temp = DataType.objects.get(standard_name="sea_water_temperature")
        self.current_direction = DataType.objects.get(
            standard_name="direction_of_sea_water_velocity",
        )

        self.buffer_type = BufferType.objects.get(name="sbe37")

        self.ds_N01_sbe37 = ErddapDataset.objects.create(
            name="N01_sbe37_all",
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
            end_time=None,
            buffer_type=self.buffer_type,
            dataset=self.ds_N01_sbe37,
            value=32.97419,
            value_time="2019-03-22 00:00:00+00",
        )
        self.ts2 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable="temperature",
            constraints={"depth=": 100.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            end_time=None,
            buffer_type=self.buffer_type,
            dataset=self.ds_N01_sbe37,
            value=5.706,
            value_time="2019-03-22 00:00:00+00",
        )

        # one with the same dataset but a different constraint
        self.ts3 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable="temperature",
            constraints={"depth=": 1.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            end_time=None,
            buffer_type=self.buffer_type,
            dataset=self.ds_N01_sbe37,
            value=3.787,
            value_time="2019-03-22 00:00:00+00",
        )

        self.ds_N01_aanderaa = ErddapDataset.objects.create(
            name="N01_aanderaa_all",
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
            end_time=None,
            buffer_type=None,
            dataset=self.ds_N01_aanderaa,
            value=18.3632,
            value_time="2019-03-22 00:00:00+00",
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
            buffer_type=self.buffer_type,
            dataset=self.ds_N01_sbe37,
        )

    def test_platform_detail_with_no_time_series(self):
        response = self.client.get("/api/platforms/A01/", format="json")

        for key in ("id", "type", "geometry", "properties"):
            self.assertIn(key, response.data, msg=f"{key} not in top level of response")

        geo = geojson.loads(response.content)

        self.assertTrue(geo.is_valid)
        self.assertEqual("Feature", geo["type"])

        for key in (
            "readings",
            "attribution",
            "mooring_site_desc",
            "ndbc_site_id",
            "uscg_light_letter",
            "uscg_light_num",
            "watch_circle_radius",
            "programs",
        ):
            self.assertIn(
                key,
                geo["properties"],
                msg=f"{key} is not in feature properties",
            )
        self.assertNotIn("geom", geo["properties"])

        self.assertEqual(0, len(geo["properties"]["readings"]))

    @my_vcr.use_cassette("platform_N01.yaml")
    def test_platform_detail_with_time_series(self):
        response = self.client.get("/api/platforms/N01/", format="json")

        for key in ("id", "type", "geometry", "properties"):
            self.assertIn(key, response.data, msg=f"{key} not in top level of response")

        geo = geojson.loads(response.content)

        self.assertTrue(geo.is_valid)
        self.assertEqual("Feature", geo["type"])

        for key in (
            "readings",
            "attribution",
            "mooring_site_desc",
            "ndbc_site_id",
            "uscg_light_letter",
            "uscg_light_num",
            "watch_circle_radius",
            "programs",
        ):
            self.assertIn(
                key,
                geo["properties"],
                msg=f"{key} is not in feature properties",
            )
        self.assertNotIn("geom", geo["properties"])

        self.assertEqual(4, len(geo["properties"]["readings"]))

        for reading in geo["properties"]["readings"]:
            self.assertIn("depth", reading)  # Ok for depth to be none

            for key in (
                "value",
                "time",
                "data_type",
                "server",
                "variable",
                "constraints",
                "dataset",
                "start_time",
                "cors_proxy_url",
            ):
                self.assertIn(
                    key,
                    reading,
                    msg=f"{key} not found in reading: {reading}",
                )
                self.assertIsNotNone(reading[key], msg=f"reading[{key}]: is none")

            self.assertIsInstance(
                reading["value"],
                float,
                msg=f"reading['value']: {reading} is not a float",
            )
            self.assertEqual(reading["server"], "http://www.neracoos.org/erddap")

            self.assertIsNotNone(
                reading["variable"],
                msg=f"{reading} is missing a variable",
            )
            self.assertIsNotNone(
                reading["dataset"],
                msg=f"{reading} is missing a dataset",
            )

            for key in ("standard_name", "short_name", "long_name", "units"):
                self.assertIn(key, reading["data_type"])

    @my_vcr.use_cassette("platform_list.yaml")
    def test_platform_list(self):
        response = self.client.get("/api/platforms/", format="json")

        geo = geojson.loads(response.content)

        self.assertTrue(geo.is_valid)
        self.assertEqual("FeatureCollection", geo["type"])

        self.assertEqual(
            60,
            len(geo["features"]),
            msg=(
                "Should be the same as the number of platforms in the fixture file. "
                "This may need to be changed after fixtures are regenerated."
            ),
        )

    def test_server_list(self):
        response = self.client.get("/api/servers/", format="json")

        self.assertEqual(2, len(response.data))
        self.assertIn(b"NERACOOS", response.content)

    def test_server_detail(self):
        response = self.client.get("/api/servers/1/", format="json")

        self.assertIn(b"NERACOOS", response.content)
        self.assertIn("name", response.data)
        self.assertIn("base_url", response.data)
        self.assertIn("url", response.data)

    @patch("deployments.tasks.refresh.single_refresh_server.delay")
    def test_server_refresh(self, refresh_server):
        response = self.client.get("/api/servers/1/refresh/", format="json")

        self.assertIn(b"NERACOOS", response.content)
        self.assertIn("name", response.data)
        self.assertIn("base_url", response.data)
        self.assertIn("url", response.data)
        refresh_server.assert_called_once()

    def test_dataset_list(self):
        response = self.client.get("/api/datasets/", format="json")

        self.assertIn(b"N01_sbe37_all", response.content)
        self.assertIn(b"NERACOOS", response.content)
        self.assertEqual(2, len(response.data))

    def test_dataset_detail(self):
        response = self.client.get(
            "/api/datasets/NERACOOS-N01_sbe37_all/",
            format="json",
        )

        self.assertIn(b"N01_sbe37_all", response.content)
        self.assertIn(b"NERACOOS", response.content)
        self.assertIn("name", response.data)
        self.assertIn("server", response.data)
        self.assertIn("name", response.data["server"])

    @my_vcr.use_cassette("dataset_detail.yaml")
    @patch("deployments.tasks.single_refresh_dataset.delay")
    def test_dataset_refresh(self, refresh_dataset):
        response = self.client.get(
            "/api/datasets/NERACOOS-N01_sbe37_all/refresh/",
            format="json",
        )
        self.assertIn(b"N01_sbe37_all", response.content)
        self.assertIn(b"NERACOOS", response.content)
        self.assertIn("name", response.data)
        self.assertIn("server", response.data)
        self.assertIn("name", response.data["server"])
        refresh_dataset.assert_called_once()
