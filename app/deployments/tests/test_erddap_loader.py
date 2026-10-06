import pytest
from django.contrib.gis.geos import Point
from django.test import TestCase

from deployments.models import DataType, ErddapServer, Platform, TimeSeries
from deployments.utils.erddap_loader import Status, add_timeseries, apply_import, plan_import

from .vcr import my_vcr

DATASET = "M01_accelerometer_all"
CONSTRAINTS = {"depth=": 0.0}
QC_CONSTRAINTS = {
    "depth=": 0.0,
    "significant_wave_height_qc=": 0,
    "dominant_wave_period_qc=": 0,
}
ERDDAP_LOCATION = (-67.87574274399701, 43.496932310216565)


def cassette():
    return my_vcr.use_cassette("erddap_loader.yaml", allow_playback_repeats=True)


@pytest.mark.django_db
class ErddapLoaderTestCase(TestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap_url = "http://www.neracoos.org/erddap"
        self.erddap_server = ErddapServer.objects.get(base_url=self.erddap_url)

    def plan(self, platform=None):
        return plan_import(self.erddap_server, DATASET, CONSTRAINTS, platform=platform)

    def test_load_dataset_from_erddap_and_create_timeseries(self):
        self.assertEqual(0, self.platform.timeseries_set.count())

        with cassette():
            add_timeseries(self.platform, self.erddap_url, DATASET, CONSTRAINTS)

        self.assertEqual(2, self.platform.timeseries_set.count())

        for ts in self.platform.timeseries_set.all():
            self.assertEqual(ts.dataset.name, DATASET)
            self.assertEqual(ts.dataset.server, self.erddap_server)
            self.assertEqual(ts.depth, 0.0)
            self.assertEqual(ts.constraints, {"depth=": 0.0, f"{ts.variable}_qc=": 0})
            self.assertIn(
                ts.variable,
                ("significant_wave_height", "dominant_wave_period"),
            )

    def test_reimport_is_unchanged(self):
        with cassette():
            add_timeseries(self.platform, self.erddap_url, DATASET, CONSTRAINTS)
            plan = self.plan(self.platform)

        self.assertEqual(plan.new, [])
        self.assertEqual(
            {row.variable for row in plan.unchanged},
            {"significant_wave_height", "dominant_wave_period"},
        )
        self.assertEqual(plan.not_in_metadata, [])

    def test_existing_timeseries_without_qc_is_changed(self):
        with cassette():
            add_timeseries(self.platform, self.erddap_url, DATASET, CONSTRAINTS)
        TimeSeries.objects.filter(platform=self.platform).update(constraints=CONSTRAINTS)

        with cassette():
            plan = self.plan(self.platform)

        self.assertEqual(len(plan.changed), 2)
        row = next(row for row in plan.changed if row.variable == "dominant_wave_period")
        self.assertEqual(
            row.changes["constraints"],
            (CONSTRAINTS, {"depth=": 0.0, "dominant_wave_period_qc=": 0}),
        )

        apply_import(plan, update=["dominant_wave_period"])

        constraints = dict(
            TimeSeries.objects.filter(platform=self.platform).values_list("variable", "constraints"),
        )
        self.assertEqual(
            constraints["dominant_wave_period"],
            {"depth=": 0.0, "dominant_wave_period_qc=": 0},
        )
        self.assertEqual(constraints["significant_wave_height"], CONSTRAINTS)

    def test_existing_timeseries_missing_from_metadata(self):
        with cassette():
            add_timeseries(self.platform, self.erddap_url, DATASET, CONSTRAINTS)
        TimeSeries.objects.filter(variable="dominant_wave_period").update(variable="old_variable")

        with cassette():
            plan = self.plan(self.platform)

        self.assertEqual([row.variable for row in plan.new], ["dominant_wave_period"])
        self.assertEqual([ts.variable for ts in plan.not_in_metadata], ["old_variable"])

    def test_location_differs_from_existing_platform(self):
        original = self.platform.geom.clone()

        with cassette():
            plan = self.plan(self.platform)

        self.assertTrue(plan.location_differs)
        self.assertGreater(plan.location_distance, 500)

        apply_import(plan)
        self.platform.refresh_from_db()
        self.assertTrue(self.platform.geom.equals_exact(original, 1e-9))

        apply_import(plan, create=[], update_location=True)
        self.platform.refresh_from_db()
        self.assertAlmostEqual(self.platform.geom.x, ERDDAP_LOCATION[0])
        self.assertAlmostEqual(self.platform.geom.y, ERDDAP_LOCATION[1])

    def test_nearby_location_does_not_differ(self):
        self.platform.geom = Point(-67.8758, 43.4968, srid=4326)
        self.platform.save()

        with cassette():
            plan = self.plan(self.platform)

        self.assertFalse(plan.location_differs)

    def test_platform_without_location_gets_one(self):
        self.platform.geom = None
        self.platform.save()

        with cassette():
            apply_import(self.plan(self.platform))

        self.platform.refresh_from_db()
        self.assertAlmostEqual(self.platform.geom.x, ERDDAP_LOCATION[0])

    def test_create_new_platform(self):
        with cassette():
            result = apply_import(self.plan(), platform_name="M01-NEW")

        platform = Platform.objects.get(name="M01-NEW")
        self.assertTrue(result.platform_created)
        self.assertEqual(platform.station_name, "M01 Jordan Basin Accelerometer")
        self.assertEqual(platform.ndbc_site_id, "44037")
        self.assertAlmostEqual(platform.geom.y, ERDDAP_LOCATION[1])
        self.assertEqual(platform.timeseries_set.count(), 2)

    def test_variables_without_data_type_are_not_imported(self):
        DataType.objects.filter(long_name="Dominant Wave Period").delete()
        data_types = DataType.objects.count()

        with cassette():
            plan = self.plan(self.platform)
        apply_import(plan)

        self.assertEqual([row.variable for row in plan.unable], ["dominant_wave_period"])
        self.assertEqual(plan.unable[0].status, Status.UNABLE)
        self.assertEqual(
            list(self.platform.timeseries_set.values_list("variable", flat=True)),
            ["significant_wave_height"],
        )
        self.assertEqual(DataType.objects.count(), data_types)

    def test_qc_constraints_on_all_variables(self):
        with cassette():
            plan = self.plan()

        constraints = {}
        for row in plan.new:
            constraints.update(row.constraints)
        self.assertEqual(constraints, QC_CONSTRAINTS)
