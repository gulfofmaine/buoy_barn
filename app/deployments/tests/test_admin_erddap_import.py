import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from deployments.models import ErddapServer, Platform

from .vcr import my_vcr

IMPORT_URL = reverse("admin:deployments_platform_import_erddap")


def cassette():
    return my_vcr.use_cassette("erddap_loader.yaml", allow_playback_repeats=True)


@pytest.mark.django_db
class ErddapImportAdminTestCase(TestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.user = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw")
        self.client.force_login(self.user)
        self.platform = Platform.objects.get(name="M01")
        self.server = ErddapServer.objects.get(base_url="http://www.neracoos.org/erddap")

    def form_data(self, **extra):
        return {
            "server": self.server.pk,
            "dataset_id": "M01_accelerometer_all",
            "constraints": json.dumps({"depth=": 0.0}),
            "platform": self.platform.pk,
            "new_platform_name": "",
            **extra,
        }

    def test_changelist_has_import_button(self):
        response = self.client.get(reverse("admin:deployments_platform_changelist"))

        self.assertContains(response, "Import from ERDDAP")

    def test_change_page_has_import_dataset_button(self):
        response = self.client.get(
            reverse("admin:deployments_platform_change", args=[self.platform.pk]),
        )

        self.assertContains(response, "Import dataset from ERDDAP")

    def test_change_action_prefills_platform(self):
        response = self.client.get(
            reverse(
                "admin:deployments_platform_actions",
                args=[self.platform.pk, "import_erddap_dataset"],
            ),
        )
        self.assertRedirects(response, f"{IMPORT_URL}?platform={self.platform.pk}")

        response = self.client.get(response["Location"])
        self.assertContains(response, f'<option value="{self.platform.pk}" selected>')

    def test_preview_shows_plan_without_saving(self):
        with cassette():
            response = self.client.post(IMPORT_URL, self.form_data(step="preview"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New timeseries")
        self.assertContains(response, "significant_wave_height_qc=")
        self.assertContains(response, "m from this platform's current location")
        self.assertContains(response, 'name="update_location"')
        self.assertEqual(self.platform.timeseries_set.count(), 0)

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    def test_apply_creates_selected_timeseries(self, mock_delay):
        data = self.form_data(step="apply")
        data["create"] = ["significant_wave_height"]

        with cassette():
            response = self.client.post(IMPORT_URL, data)

        self.assertRedirects(
            response,
            reverse("admin:deployments_platform_change", args=[self.platform.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            list(self.platform.timeseries_set.values_list("variable", flat=True)),
            ["significant_wave_height"],
        )
        mock_delay.assert_called_once()

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    def test_apply_creates_new_platform(self, mock_delay):
        data = self.form_data(step="apply", platform="", new_platform_name="M01-NEW")
        data["create"] = ["significant_wave_height", "dominant_wave_period"]

        with cassette():
            response = self.client.post(IMPORT_URL, data)

        platform = Platform.objects.get(name="M01-NEW")
        self.assertRedirects(
            response,
            reverse("admin:deployments_platform_change", args=[platform.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(platform.timeseries_set.count(), 2)
        self.assertIsNotNone(platform.geom)

    def test_requires_platform_choice(self):
        response = self.client.post(IMPORT_URL, self.form_data(step="preview", platform=""))

        self.assertContains(response, "Choose an existing platform or enter a new platform name")

    def test_rejects_existing_platform_name(self):
        response = self.client.post(
            IMPORT_URL,
            self.form_data(step="preview", platform="", new_platform_name="M01"),
        )

        self.assertContains(response, "already exists")

    def test_rejects_non_object_constraints(self):
        response = self.client.post(IMPORT_URL, self.form_data(constraints="[1, 2]"))

        self.assertContains(response, "Constraints must be a JSON object")

    def test_requires_permissions(self):
        staff = get_user_model().objects.create_user("staff", password="pw", is_staff=True)
        self.client.force_login(staff)

        response = self.client.get(IMPORT_URL)

        self.assertEqual(response.status_code, 403)
