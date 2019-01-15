import geojson
from rest_framework.test import APITestCase

from deployments.models import Platform, TimeSeries, ErddapServer, DataType, BufferType
from .vcr import my_vcr


# my_vcr = vcr.VCR(cassette_library_dir='deployments/tests/cassettes/',
#                  match_on=['method', 'scheme', 'host', 'port', 'path'])


class BuoyBarnPlatformAPITestCase(APITestCase):
    fixtures = ["platforms", "erddapservers"]

    def setUp(self):
        self.platform = Platform.objects.get(name="N01")
        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap"
        )

        # self.conductivity = DataType.objects.get(standard_name='sea_water_electrical_conductivity')
        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")
        self.water_temp = DataType.objects.get(standard_name="sea_water_temperature")
        self.current_direction = DataType.objects.get(
            standard_name="direction_of_sea_water_velocity"
        )

        self.buffer_type = BufferType.objects.get(name="sbe37")

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
            erddap_dataset="N01_sbe37_all",
            erddap_server=self.erddap,
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
            erddap_dataset="N01_sbe37_all",
            erddap_server=self.erddap,
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
            erddap_dataset="N01_sbe37_all",
            erddap_server=self.erddap,
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
            erddap_dataset="N01_aanderaa_all",
            erddap_server=self.erddap,
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
            erddap_dataset="N01_sbe37_all",
            erddap_server=self.erddap,
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
                key, geo["properties"], msg=f"{key} is not in feature properties"
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
                key, geo["properties"], msg=f"{key} is not in feature properties"
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
            ):
                self.assertIn(
                    key, reading, msg=f"{key} not found in reading: {reading}"
                )
                self.assertIsNotNone(reading[key], msg=f"reading[{key}]: is none")

            self.assertIsInstance(
                reading["value"],
                float,
                msg=f"reading['value']: {reading} is not a float",
            )
            self.assertEqual(reading["server"], "http://www.neracoos.org/erddap")

            self.assertIsNotNone(
                reading["variable"], msg=f"{reading} is missing a variable"
            )
            self.assertIsNotNone(
                reading["dataset"], msg=f"{reading} is missing a dataset"
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
            msg="Should be the same as the number of platforms in the fixture file. This may need to be changed after fixtures are regenerated.",
        )


class BuoyBarn500APITestCase(APITestCase):
    """ Test that the server doesn't return a 500 when an ERDDAP datasource doesn't return any rows"""

    fixtures = ["platforms", "erddapservers"]

    def setUp(self):
        self.platform = Platform.objects.get(name="44005")
        self.erddap = ErddapServer.objects.get(
            base_url="https://coastwatch.pfeg.noaa.gov/erddap"
        )
        self.data_type = DataType.objects.get(standard_name="visibility_in_air")

        self.ts = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.data_type,
            variable="vis",
            constraints={"station=": "41010"},
            depth=None,
            start_time="1970-02-26 20:00:00+00",
            end_time=None,
            buffer_type=None,
            erddap_dataset="cwwcNDBCMet",
            erddap_server=self.erddap,
        )

    @my_vcr.use_cassette("no_rows_returned.yaml")
    def test_erddap_returns_no_rows(self):
        response = self.client.get("/api/platforms/44005/")

        for key in ("id", "type", "geometry", "properties"):
            self.assertIn(key, response.data, msg=f"{key} not in top level of response")

        geo = geojson.loads(response.content)

        self.assertTrue(geo.is_valid)
        self.assertEqual("Feature", geo["type"])

        self.assertEqual(1, len(geo["properties"]["readings"]))

        for reading in geo["properties"]["readings"]:
            self.assertIsNone(reading["value"])
            self.assertIsNone(reading["value"])

