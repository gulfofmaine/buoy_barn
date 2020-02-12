from django.test import TestCase

import pytest

from deployments.models import Platform, ErddapServer
from deployments.utils.erddap_loader import add_timeseries
from .vcr import my_vcr


@pytest.mark.django_db
class ErddapLoaderTestCase(TestCase):
    fixtures = ["platforms", "erddapservers"]

    def setUp(self):
        self.platform = Platform.objects.get(name="N01")
        self.erddap_url = "http://www.neracoos.org/erddap"
        self.erddap_server = ErddapServer.objects.get(base_url=self.erddap_url)

    @my_vcr.use_cassette("erddap_loader.yaml")
    def test_load_dataset_from_erddap_and_create_timeseries(self):
        self.assertEqual(0, self.platform.timeseries_set.count())

        constraints = {"depth=": 0.0}
        dataset = "N01_accelerometer_all"

        add_timeseries(self.platform, self.erddap_url, dataset, constraints)

        self.assertEqual(2, self.platform.timeseries_set.count())

        for ts in self.platform.timeseries_set.all():

            self.assertEqual(ts.constraints, constraints)
            self.assertEqual(ts.dataset.name, dataset)
            self.assertEqual(ts.dataset.server, self.erddap_server)
            self.assertIn(
                ts.variable, ("significant_wave_height", "dominant_wave_period")
            )
