from datetime import datetime
from pathlib import Path

import pandas as pd
from django.test import TestCase
from freezegun import freeze_time

from forecasts.utils import erddap

df = pd.read_csv(Path(__file__).parents[0] / "test_griddap_attributes.csv")


class ErddapUtilsTestCase(TestCase):
    def test_attribute_value(self):
        time = erddap.attribute_value(df, "time_coverage_end")
        self.assertEqual(time, "2019-01-11T00:00:00Z")

        precision = erddap.attribute_value(df, "geospatial_lat_resolution")
        self.assertEqual(precision, 0.05)

    @freeze_time("2019-01-09 00:00:00")
    def test_coverage_time(self):
        coverage_time = erddap.coverage_time_str(df)

        self.assertEqual(
            coverage_time,
            "[(2019-01-09T00:00:00Z):1:(2019-01-11T00:00:00Z)]",
            msg="Coverage time should be time_coverage_start or current day, whichever is later",
        )

    @freeze_time("2019-01-07 00:00:00")
    def test_coverage_later_time(self):
        coverage_time = erddap.coverage_time_str(df)

        self.assertEqual(
            coverage_time,
            "[(2019-01-08T00:00:00Z):1:(2019-01-11T00:00:00Z)]",
            msg="Coverage should be time_coverage_start or current day, whichever is later",
        )

    def test_coordinate_str(self):
        coord_str = erddap.coordinates_str(df, 43.650608, -70.250745)

        self.assertEqual(coord_str, "[(43.65):1:(43.65)][(-70.25):1:(-70.25)]")

    def test_parse_time(self):
        time_str = "2019-01-10T00:00:00Z"
        time = datetime(2019, 1, 10, 00, 00, 00)

        parsed = erddap.parse_time(time_str)

        self.assertEqual(time, parsed)
