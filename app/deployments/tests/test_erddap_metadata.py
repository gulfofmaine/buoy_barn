import csv
import io

import pytest
from django.contrib.gis.geos import Point
from django.test import TestCase

from deployments.models import DataType
from deployments.utils import erddap_metadata as metadata

IOOS_FLAGS = [
    ("flag_values", "byte", "1, 2, 3, 4, 9"),
    ("flag_meanings", "String", "PASS NOT_EVALUATED SUSPECT FAIL MISSING"),
]


def info_csv(global_attrs=(), variables=None) -> str:
    """Build an ERDDAP info CSV from (name, type, value) attribute tuples"""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Row Type", "Variable Name", "Attribute Name", "Data Type", "Value"])
    for name, data_type, value in global_attrs:
        writer.writerow(["attribute", "NC_GLOBAL", name, data_type, value])
    for variable, attrs in (variables or {}).items():
        writer.writerow(["variable", variable, "", "double", ""])
        for name, data_type, value in attrs:
            writer.writerow(["attribute", variable, name, data_type, value])
    return out.getvalue()


def make_info(global_attrs=(), variables=None) -> metadata.DatasetInfo:
    return metadata.parse_info_csv("test_dataset", info_csv(global_attrs, variables))


def qartod_test(name):
    return name, IOOS_FLAGS


NAVD88_VARIABLES = {
    "time": [("standard_name", "String", "time")],
    "latitude": [("standard_name", "String", "latitude")],
    "longitude": [("standard_name", "String", "longitude")],
    "navd88_meters": [
        (
            "ancillary_variables",
            "String",
            "navd88_meters_qartod_flat_line_test navd88_meters_qartod_spike_test "
            "navd88_meters_qartod_gross_range_test navd88_meters_qartod_rate_of_change_test",
        ),
        ("datum", "String", "NAVD88"),
        ("long_name", "String", "Sea surface height above geopotential datum"),
        ("standard_name", "String", "sea_surface_height_above_geopotential_datum"),
        ("tidal_datum_offsets_meters", "String", '{"mhhw": 1.469, "mllw": -1.573}'),
        ("units", "String", "m"),
    ],
    **{
        f"navd88_meters_qartod_{test}_test": IOOS_FLAGS
        for test in ("flat_line", "spike", "gross_range", "rate_of_change")
    },
}


class ParseInfoTestCase(TestCase):
    def test_casts_values_by_type(self):
        info = make_info(
            [("latitude", "double", "43.5"), ("title", "String", "A, B")],
            {"x_qc": [("flag_values", "byte", "0, 1, 2")]},
        )

        self.assertEqual(info.globals["latitude"], 43.5)
        self.assertEqual(info.globals["title"], "A, B")
        self.assertEqual(info.variables["x_qc"]["flag_values"], [0, 1, 2])


class QartodConstraintsTestCase(TestCase):
    def test_neracoos_qc_flag(self):
        info = make_info(
            variables={
                "salinity": [("ancillary_variables", "String", "salinity_qc")],
                "salinity_qc": [
                    ("flag_values", "byte", "0, 1, 2, 3, 40, 60, 99"),
                    (
                        "flag_meanings",
                        "String",
                        "quality_good out_of_range sensor_nonfunctional "
                        "algorithm_failure_no_infl_pt other_auto_qc off_station "
                        "suspect_or_other_manual_qc",
                    ),
                ],
            },
        )

        constraints, warnings = metadata.qartod_constraints(info, "salinity")

        self.assertEqual(constraints, {"salinity_qc=": 0})
        self.assertEqual(warnings, [])

    def test_each_ioos_qartod_test_is_constrained(self):
        info = make_info(variables=NAVD88_VARIABLES)

        constraints, warnings = metadata.qartod_constraints(info, "navd88_meters")

        self.assertEqual(
            constraints,
            {
                "navd88_meters_qartod_flat_line_test<=": 2,
                "navd88_meters_qartod_spike_test<=": 2,
                "navd88_meters_qartod_gross_range_test<=": 2,
                "navd88_meters_qartod_rate_of_change_test<=": 2,
            },
        )
        self.assertEqual(warnings, [])

    def test_aggregate_listed_in_ancillary_variables(self):
        info = make_info(
            variables={
                "temp": [("ancillary_variables", "String", "temp_rollup")],
                "temp_rollup": [
                    ("standard_name", "String", "aggregate_quality_flag"),
                    *IOOS_FLAGS,
                ],
            },
        )

        constraints, _ = metadata.qartod_constraints(info, "temp")

        self.assertEqual(constraints, {"temp_rollup<=": 2})

    def test_unlisted_aggregate_matched_by_name(self):
        info = make_info(
            variables={
                "temp": [("ancillary_variables", "String", "temp_qartod_spike_test")],
                "temp_qartod_spike_test": IOOS_FLAGS,
                "temp_qartod_aggregate": [
                    ("standard_name", "String", "aggregate_quality_flag"),
                    *IOOS_FLAGS,
                ],
                "salinity": [],
                "salinity_qartod_aggregate": [
                    ("standard_name", "String", "aggregate_quality_flag"),
                    *IOOS_FLAGS,
                ],
            },
        )

        self.assertEqual(
            metadata.qartod_constraints(info, "temp")[0],
            {"temp_qartod_spike_test<=": 2, "temp_qartod_aggregate<=": 2},
        )
        self.assertEqual(
            metadata.qartod_constraints(info, "salinity")[0],
            {"salinity_qartod_aggregate<=": 2},
        )

    def test_single_unlisted_aggregate_applies_to_the_dataset(self):
        info = make_info(
            variables={
                "temp": [],
                "salinity": [],
                "qc_rollup": [
                    ("standard_name", "String", "aggregate_quality_flag"),
                    *IOOS_FLAGS,
                ],
            },
        )

        self.assertEqual(metadata.qartod_constraints(info, "temp")[0], {"qc_rollup<=": 2})
        self.assertEqual(metadata.qartod_constraints(info, "salinity")[0], {"qc_rollup<=": 2})

    def test_several_unassignable_aggregates_warn(self):
        aggregate = [("standard_name", "String", "aggregate_quality_flag"), *IOOS_FLAGS]
        info = make_info(
            variables={"temp": [], "qc_rollup_a": aggregate, "qc_rollup_b": aggregate},
        )

        assigned, warnings = metadata.aggregate_flags(info)

        self.assertEqual(assigned, {"temp": []})
        self.assertEqual(len(warnings), 1)
        self.assertIn("qc_rollup_a", warnings[0])
        self.assertIn("qc_rollup_b", warnings[0])

    def test_no_flags_warns(self):
        info = make_info(variables={"temp": []})

        constraints, warnings = metadata.qartod_constraints(info, "temp")

        self.assertEqual(constraints, {})
        self.assertEqual(warnings, ["No QC flag variables found"])

    def test_unparseable_flags_warn(self):
        info = make_info(
            variables={
                "temp": [("ancillary_variables", "String", "temp_qc")],
                "temp_qc": [
                    ("flag_values", "byte", "1, 2"),
                    ("flag_meanings", "String", "bad worse"),
                ],
            },
        )

        constraints, warnings = metadata.qartod_constraints(info, "temp")

        self.assertEqual(constraints, {})
        self.assertIn("no flag meaning pass or good", warnings[0])


class DataVariablesTestCase(TestCase):
    def test_excludes_coordinates_and_flags(self):
        info = make_info(
            [("cdm_timeseries_variables", "String", "station, longitude, latitude")],
            {
                **NAVD88_VARIABLES,
                "station": [("cf_role", "String", "timeseries_id")],
                "depth": [("standard_name", "String", "depth")],
                "rollup": [("standard_name", "String", "aggregate_quality_flag"), *IOOS_FLAGS],
            },
        )

        self.assertEqual(metadata.data_variables(info), ["navd88_meters"])


class TidalDatumsTestCase(TestCase):
    def test_reads_offsets(self):
        info = make_info(variables=NAVD88_VARIABLES)

        datums, warnings = metadata.tidal_datums(info, "navd88_meters")

        self.assertEqual(datums, {"datum_mhhw_meters": 1.469, "datum_mllw_meters": -1.573})
        self.assertEqual(warnings, [])

    def test_unknown_datum_warns(self):
        info = make_info(
            variables={"wl": [("tidal_datum_offsets_meters", "String", '{"mhhw": 1, "stnd": 2}')]},
        )

        datums, warnings = metadata.tidal_datums(info, "wl")

        self.assertEqual(datums, {"datum_mhhw_meters": 1.0})
        self.assertEqual(warnings, ["Unknown tidal datum 'stnd'"])

    def test_malformed_json_warns(self):
        info = make_info(variables={"wl": [("tidal_datum_offsets_meters", "String", "{mhhw: 1")]})

        datums, warnings = metadata.tidal_datums(info, "wl")

        self.assertEqual(datums, {})
        self.assertIn("Unable to read", warnings[0])

    def test_no_datums(self):
        info = make_info(variables={"wl": []})

        self.assertEqual(metadata.tidal_datums(info, "wl"), ({}, []))


class PlatformLocationTestCase(TestCase):
    def test_latitude_longitude_attributes(self):
        info = make_info([("latitude", "double", "43.5"), ("longitude", "double", "-70.1")])

        point, source = metadata.platform_location(info)

        self.assertEqual((point.x, point.y), (-70.1, 43.5))
        self.assertEqual(source, "latitude/longitude attributes")

    def test_geospatial_bounds(self):
        info = make_info(
            [
                ("geospatial_lat_min", "double", "43.0"),
                ("geospatial_lat_max", "double", "44.0"),
                ("geospatial_lon_min", "double", "-71.0"),
                ("geospatial_lon_max", "double", "-70.0"),
            ],
        )

        point, source = metadata.platform_location(info)

        self.assertEqual((point.x, point.y), (-70.5, 43.5))
        self.assertEqual(source, "middle of geospatial bounds")

    def test_no_location(self):
        self.assertEqual(metadata.platform_location(make_info()), (None, ""))

    def test_distance(self):
        distance = metadata.distance_meters(
            Point(-70.0, 43.0, srid=4326),
            Point(-70.0, 43.1, srid=4326),
        )

        self.assertAlmostEqual(distance, 11_119, delta=5)


@pytest.mark.django_db
class MatchDataTypeTestCase(TestCase):
    def setUp(self):
        self.data_type = DataType.objects.create(
            standard_name="test_water_level",
            short_name="TWL",
            long_name="Test Water Level",
            units="m",
        )
        DataType.objects.create(
            standard_name="test_water_level",
            short_name="TWL",
            long_name="Test Water Level",
            units="ft",
        )

    def test_matches_standard_name_and_prefers_units(self):
        data_type, reason = metadata.match_data_type(
            {"standard_name": "test_water_level", "units": "m"},
        )

        self.assertEqual(data_type, self.data_type)
        self.assertIsNone(reason)

    def test_falls_back_to_long_name(self):
        data_type, _ = metadata.match_data_type(
            {"standard_name": "unknown", "long_name": "Test Water Level", "units": "m"},
        )

        self.assertEqual(data_type, self.data_type)

    def test_never_creates_data_types(self):
        count = DataType.objects.count()

        data_type, reason = metadata.match_data_type(
            {"standard_name": "made_up", "long_name": "Made up", "units": "m"},
        )

        self.assertIsNone(data_type)
        self.assertIn("Unable to import", reason)
        self.assertEqual(DataType.objects.count(), count)
