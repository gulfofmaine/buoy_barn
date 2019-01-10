from pathlib import Path

from django.test import TestCase
from freezegun import freeze_time
import pandas as pd

from forecasts.utils import erddap


df = pd.read_csv(Path(__file__).parents[0] / "test_griddap_attributes.csv")


class ErddapUtilsTestCase(TestCase):
    def test_attribute_value(self):
        time = erddap.attribute_value(df, "time_coverage_end")
        self.assertEquals(time, "2019-01-11T00:00:00Z")

        precision = erddap.attribute_value(df, "geospatial_lat_resolution")
        self.assertEquals(precision, 0.05)

    @freeze_time("2019-01-09 00:00:00")
    def test_coverage_time(self):
        coverage_time = erddap.coverage_time_str(df)

        self.assertEquals(
            coverage_time,
            "[(2019-01-09T00:00:00Z):1:(2019-01-11T00:00:00Z)]",
            msg="Coverage time should be time_coverage_start or current day, whichever is later",
        )

    @freeze_time("2019-01-07 00:00:00")
    def test_coverage_later_time(self):
        coverage_time = erddap.coverage_time_str(df)

        self.assertEquals(
            coverage_time,
            "[(2019-01-08T00:00:00Z):1:(2019-01-11T00:00:00Z)]",
            msg="Coverage should be time_coverage_start or current day, whichever is later",
        )

    def test_coordinate_Str(self):
        coord_str = erddap.coordinate_str(df, 43.650608, -70.250745)

        self.assertEquals(coord_str, "[(43.65):1:(-70.25)]")

