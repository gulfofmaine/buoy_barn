from unittest.mock import patch

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase

from deployments.admin import ErddapDatasetAdmin, ErddapServerAdmin, PlatformAdmin
from deployments.models import (
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    TimeSeries,
)


def _make_request(user=None):
    """Create a mock request with message storage."""
    factory = RequestFactory()
    request = factory.get("/")
    request.session = {}
    messages = FallbackStorage(request)
    request._messages = messages
    if user is not None:
        request.user = user
    return request


@pytest.mark.django_db
class PlatformAdminObjectActionsTestCase(TestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.site = AdminSite()
        self.admin = PlatformAdmin(Platform, self.site)

        self.platform = Platform.objects.get(name="M01")
        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap",
        )
        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")

        self.dataset = ErddapDataset.objects.create(
            name="M01_sbe37_all",
            server=self.erddap,
        )
        TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.salinity,
            variable="salinity",
            constraints={"depth=": 100.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            dataset=self.dataset,
        )

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    def test_refresh_platform_datasets_queues_datasets(self, mock_delay):
        request = _make_request()
        self.admin.refresh_platform_datasets(request, self.platform)

        mock_delay.assert_called_once_with(self.dataset.id)

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    def test_refresh_platform_datasets_no_timeseries(self, mock_delay):
        empty_platform = Platform.objects.create(
            name="EMPTY",
            mooring_site_desc="Empty platform",
        )
        request = _make_request()
        self.admin.refresh_platform_datasets(request, empty_platform)

        mock_delay.assert_not_called()

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    def test_refresh_platform_datasets_deduplicates(self, mock_delay):
        """Multiple timeseries on the same dataset should only queue one refresh."""
        water_temp = DataType.objects.get(standard_name="sea_water_temperature")
        TimeSeries.objects.create(
            platform=self.platform,
            data_type=water_temp,
            variable="temperature",
            constraints={"depth=": 100.0},
            depth=1,
            start_time="2004-06-03 21:00:00+00",
            dataset=self.dataset,
        )

        request = _make_request()
        self.admin.refresh_platform_datasets(request, self.platform)

        mock_delay.assert_called_once_with(self.dataset.id)


@pytest.mark.django_db
class ErddapDatasetAdminObjectActionsTestCase(TestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.site = AdminSite()
        self.admin = ErddapDatasetAdmin(ErddapDataset, self.site)

        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap",
        )
        self.dataset = ErddapDataset.objects.create(
            name="M01_sbe37_all",
            server=self.erddap,
        )

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    def test_refresh_erddap_dataset_queues_task(self, mock_delay):
        request = _make_request()
        self.admin.refresh_erddap_dataset(request, self.dataset)

        mock_delay.assert_called_once_with(self.dataset.id, healthcheck=False)


@pytest.mark.django_db
class ErddapServerAdminObjectActionsTestCase(TestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.site = AdminSite()
        self.admin = ErddapServerAdmin(ErddapServer, self.site)

        self.erddap = ErddapServer.objects.get(
            base_url="http://www.neracoos.org/erddap",
        )

    @patch("deployments.tasks.refresh.refresh_server.delay")
    def test_refresh_erddap_server_queues_task(self, mock_delay):
        request = _make_request()
        self.admin.refresh_erddap_server(request, self.erddap)

        mock_delay.assert_called_once_with(self.erddap.id, healthcheck=False)
