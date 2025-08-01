import pytest
from django.test import TestCase

from deployments.models import (
    BufferType,
    DataType,
    ErddapDataset,
    ErddapServer,
    MooringType,
    Platform,
    Program,
    ProgramAttribution,
    StationType,
    TimeSeries,
)


@pytest.mark.django_db
class ProgramTestCase(TestCase):
    def setUp(self):
        self.program = Program.objects.create(
            name="NERACOOS",
            website="http://neracoos.org",
        )

    def test_program_attributes(self):
        neracoos = Program.objects.get(name="NERACOOS")

        self.assertEqual(neracoos.name, "NERACOOS")
        self.assertEqual(neracoos.website, "http://neracoos.org")

    def test_program_str(self):
        neracoos = Program.objects.get(name="NERACOOS")

        self.assertEqual(str(neracoos), "NERACOOS")

    def test_program_json(self):
        neracoos = Program.objects.get(name="NERACOOS")

        self.assertIn("name", neracoos.json)
        self.assertIn("website", neracoos.json)

        self.assertEqual(neracoos.json["name"], "NERACOOS")
        self.assertIn("http://neracoos.org", neracoos.json["website"])


@pytest.mark.django_db
class PlatformTestCase(TestCase):
    def setUp(self):
        self.platform = Platform.objects.create(
            name="N01",
            mooring_site_desc="Northeast Channel",
            geom="SRID=4326;POINT(-65.9 42.34)",
        )

        self.other_platform = Platform.objects.create(
            name="A01",
            mooring_site_desc="MAssachusetts Bay",
        )

    def test_platform_str(self):
        n01 = Platform.objects.get(name="N01")

        self.assertEqual(str(n01), "N01")

    def test_platform_attributes(self):
        n01 = Platform.objects.get(name="N01")

        self.assertEqual(self.platform.name, n01.name)

    def test_location(self):
        n01 = Platform.objects.get(name="N01")

        self.assertIsNotNone(n01.location)
        self.assertEqual(n01.location.x, -65.9)
        self.assertEqual(n01.location.y, 42.34)
        self.assertEqual(n01.location.srid, 4326)

    def test_platform_null_location(self):
        a01 = Platform.objects.get(name="A01")

        self.assertIsNone(a01.location)


@pytest.mark.django_db
class ProgramAttributionTestCase(TestCase):
    fixtures = ["programs", "platforms"]

    def setUp(self):
        self.platform = Platform.objects.get(name="N01")

        self.neracoos = Program.objects.get(name="NERACOOS")

        self.attribution = ProgramAttribution.objects.create(
            program=self.neracoos,
            platform=self.platform,
            attribution="Managed by NERACOOS",
        )

    def test_attribution_str(self):
        attribution_string = str(self.attribution)

        self.assertIn("N01", attribution_string)
        self.assertIn("NERACOOS", attribution_string)

    def test_attribution_json(self):
        attribution = ProgramAttribution.objects.get(
            program=self.neracoos,
            platform=self.platform,
        )

        self.assertIn("program", attribution.json)
        self.assertEqual("NERACOOS", attribution.json["program"]["name"])

        self.assertIn("attribution", attribution.json)
        self.assertIn("Managed", attribution.json["attribution"])


@pytest.mark.django_db
class MooringTypeTestCase(TestCase):
    def setUp(self):
        self.mooring = MooringType.objects.get(name="Slack")

    def test_mooring_str(self):
        self.assertEqual(str(self.mooring), "Slack")


@pytest.mark.django_db
class StationTypeTestCase(TestCase):
    def setUp(self):
        self.station = StationType.objects.get(name="Surface Mooring")

    def test_station_str(self):
        self.assertEqual(str(self.station), "Surface Mooring")


@pytest.mark.django_db
class DataTypeTestCase(TestCase):
    def test_data_str(self):
        temp = DataType.objects.get(standard_name="air_temperature")

        self.assertIn("air_temperature", str(temp))
        self.assertIn("Air Temperature", str(temp))
        self.assertIn("celsius", str(temp))

    def test_data_json(self):
        temp = DataType.objects.get(standard_name="air_temperature")

        self.assertIn("standard_name", temp.json)
        self.assertEqual("air_temperature", temp.json["standard_name"])

        self.assertIn("short_name", temp.json)
        self.assertEqual("AT", temp.json["short_name"])

        self.assertIn("long_name", temp.json)
        self.assertEqual("Air Temperature", temp.json["long_name"])

        self.assertIn("units", temp.json)
        self.assertEqual("celsius", temp.json["units"])


@pytest.mark.django_db
class BufferTypeTestCase(TestCase):
    def test_buffer_str(self):
        buffer = BufferType.objects.get(name="doppler")

        self.assertEqual(str(buffer), "doppler")


@pytest.mark.django_db
class ErddapServerTestCase(TestCase):
    fixtures = ["programs"]

    def setUp(self):
        self.program = Program.objects.get(name="NERACOOS")

        self.server_with_name = ErddapServer.objects.create(
            name="NERACOOS",
            base_url="http://www.neracoos.org/erddap",
            program=self.program,
            contact="Eric",
        )

        self.server_without_name = ErddapServer.objects.create(
            base_url="http://www.neracoos.org/erddap",
        )

    def test_server_str_with_name(self):
        self.assertEqual(str(self.server_with_name), "NERACOOS")

    def test_server_str_without_name(self):
        self.assertEqual(
            str(self.server_without_name),
            "http://www.neracoos.org/erddap",
        )

    def test_server_connection(self):
        from erddapy import ERDDAP  # noqa: PLC0415

        self.assertIsInstance(self.server_with_name.connection(), ERDDAP)


@pytest.mark.django_db
class TimeSeriesTestCase(TestCase):
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

    def test_timeseries_str(self):
        self.assertIn("N01", str(self.ts1))
        self.assertIn("1", str(self.ts1))
