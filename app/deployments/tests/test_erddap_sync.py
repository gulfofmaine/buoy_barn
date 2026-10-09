from unittest.mock import patch

import pytest
import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from deployments.models import ErddapDataset, ErddapServer, Platform, TimeSeries
from deployments.utils import erddap_metadata
from deployments.utils.erddap_loader import Status, add_timeseries
from deployments.utils.erddap_sync import KEEP, apply_sync, plan_sync

from .vcr import my_vcr

DATASET = "M01_accelerometer_all"
ERDDAP_URL = "http://www.neracoos.org/erddap"
CONSTRAINTS = {"depth=": 0.0}


def cassette():
    return my_vcr.use_cassette("erddap_loader.yaml", allow_playback_repeats=True)


class SyncTestMixin:
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.server = ErddapServer.objects.get(base_url=ERDDAP_URL)
        with cassette():
            add_timeseries(self.platform, ERDDAP_URL, DATASET, CONSTRAINTS)
        # add_timeseries fills in the blank station name, blank it again to sync it
        Platform.objects.filter(pk=self.platform.pk).update(station_name="")
        self.platform.refresh_from_db()

    def sync(self):
        with cassette():
            return plan_sync(self.platform)


@pytest.mark.django_db
class PlanSyncTestCase(SyncTestMixin, TestCase):
    def test_up_to_date_platform(self):
        sync = self.sync()

        self.assertEqual(len(sync.groups), 1)
        group = sync.groups[0]
        self.assertEqual(group.constraints, CONSTRAINTS)
        self.assertEqual(len(group.plan.unchanged), 2)
        self.assertEqual(sync.errors, [])

    def test_changed_timeseries_are_selected(self):
        TimeSeries.objects.filter(platform=self.platform).update(constraints=CONSTRAINTS)

        sync = self.sync()
        group = sync.groups[0]

        self.assertEqual(len(group.plan.changed), 2)
        self.assertTrue(all(row.selected for row in group.plan.changed))

        apply_sync(
            sync,
            update={(group.id, "significant_wave_height"), (group.id, "dominant_wave_period")},
        )

        for ts in TimeSeries.objects.filter(platform=self.platform):
            self.assertEqual(ts.constraints, {"depth=": 0.0, f"{ts.variable}_qc=": 0})

    def test_new_variables_are_offered_unselected(self):
        TimeSeries.objects.filter(variable="dominant_wave_period").delete()

        sync = self.sync()
        group = sync.groups[0]

        self.assertEqual([row.variable for row in group.plan.new], ["dominant_wave_period"])
        self.assertFalse(group.plan.new[0].selected)

        apply_sync(sync)
        self.assertEqual(self.platform.timeseries_set.count(), 1)

        apply_sync(sync, create={(group.id, "dominant_wave_period")})
        self.assertEqual(self.platform.timeseries_set.count(), 2)

    def test_constraint_groups_are_planned_separately(self):
        ts = TimeSeries.objects.get(platform=self.platform, variable="dominant_wave_period")
        ts.pk = None
        ts.constraints = {"depth=": 20.0, "dominant_wave_period_qc=": 0}
        ts.depth = 20.0
        ts.save()

        with patch(
            "deployments.utils.erddap_sync.metadata.fetch_dataset_info",
            wraps=erddap_metadata.fetch_dataset_info,
        ) as fetch:
            sync = self.sync()

        fetch.assert_called_once()
        self.assertEqual(
            [group.constraints for group in sync.groups],
            [{"depth=": 0.0}, {"depth=": 20.0}],
        )
        self.assertNotEqual(sync.groups[0].id, sync.groups[1].id)
        for group in sync.groups:
            self.assertEqual(group.plan.not_in_metadata, [])

        deep = sync.groups[1].plan
        self.assertEqual([row.variable for row in deep.unchanged], ["dominant_wave_period"])
        self.assertEqual([row.variable for row in deep.new], ["significant_wave_height"])

    def test_unavailable_dataset_is_reported(self):
        other = ErddapDataset.objects.create(name="gone", server=self.server)
        existing = TimeSeries.objects.filter(platform=self.platform).first()
        TimeSeries.objects.create(
            platform=self.platform,
            data_type=existing.data_type,
            variable="anything",
            dataset=other,
        )
        real_fetch = erddap_metadata.fetch_dataset_info

        def fetch(server, dataset_id):
            if dataset_id == "gone":
                raise requests.HTTPError("404 Not Found")
            return real_fetch(server, dataset_id)

        with patch("deployments.utils.erddap_sync.metadata.fetch_dataset_info", side_effect=fetch):
            sync = self.sync()

        self.assertEqual([error.dataset for error in sync.errors], [other])
        self.assertEqual(len(sync.groups), 1)

    def test_field_choices(self):
        sync = self.sync()
        choices = {choice.name: choice for choice in sync.fields}

        station = choices["station_name"]
        self.assertEqual(station.current, "")
        self.assertEqual(station.default, station.options[0].id)
        self.assertEqual(
            station.options[0].sources,
            [f'{self.server.name} - {DATASET} {{"depth=": 0.0}}'],
        )

        mooring = choices["mooring_site_desc"]
        self.assertEqual(mooring.current, "Jordan Basin")
        self.assertEqual(mooring.default, KEEP)

        apply_sync(sync, fields={"mooring_site_desc": mooring.options[0].id})

        self.platform.refresh_from_db()
        self.assertTrue(self.platform.mooring_site_desc.startswith("Ocean observation data"))
        self.assertEqual(self.platform.station_name, "")

    def test_location_choice(self):
        original = self.platform.geom.clone()

        sync = self.sync()

        self.assertTrue(sync.location.differs)
        self.assertEqual(sync.location.default, KEEP)
        self.assertEqual(len(sync.location.options), 1)

        apply_sync(sync)
        self.platform.refresh_from_db()
        self.assertTrue(self.platform.geom.equals_exact(original, 1e-9))

        result = apply_sync(sync, location=sync.location.options[0].id)
        self.platform.refresh_from_db()
        self.assertTrue(result.location_updated)
        self.assertAlmostEqual(self.platform.geom.y, 43.496932310216565)

    def test_platform_without_location_defaults_to_erddap(self):
        Platform.objects.filter(pk=self.platform.pk).update(geom=None)
        self.platform.refresh_from_db()

        sync = self.sync()

        self.assertEqual(sync.location.default, sync.location.options[0].id)

    def test_single_import_defaults_are_unchanged(self):
        TimeSeries.objects.filter(variable="dominant_wave_period").delete()
        from deployments.utils.erddap_loader import plan_import  # noqa: PLC0415

        with cassette():
            plan = plan_import(self.server, DATASET, CONSTRAINTS, platform=self.platform)

        self.assertTrue(plan.new[0].selected)
        self.assertEqual(plan.new[0].status, Status.NEW)


@pytest.mark.django_db
class SyncAdminTestCase(SyncTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw")
        self.client.force_login(self.user)
        self.url = reverse("admin:deployments_platform_sync_erddap", args=[self.platform.pk])

    def test_change_page_has_sync_button(self):
        response = self.client.get(reverse("admin:deployments_platform_change", args=[self.platform.pk]))

        self.assertContains(response, "Sync with ERDDAP")

    def test_sync_action_redirects(self):
        response = self.client.get(
            reverse("admin:deployments_platform_actions", args=[self.platform.pk, "sync_with_erddap"]),
        )

        self.assertRedirects(response, self.url, fetch_redirect_response=False)

    def test_preview(self):
        TimeSeries.objects.filter(platform=self.platform).update(constraints=CONSTRAINTS)

        with cassette():
            response = self.client.get(self.url)

        group = response.context["sync"].groups[0]
        self.assertContains(response, DATASET)
        self.assertContains(
            response,
            f'<input type="checkbox" name="update" value="{group.id}:dominant_wave_period" checked>',
        )
        self.assertContains(response, 'name="field__station_name"')
        self.assertContains(response, 'name="location"')
        self.assertContains(response, "more than 500 m")
        self.assertContains(response, "Update selected")

    @patch("deployments.tasks.refresh.refresh_dataset.delay")
    def test_apply_selected(self, mock_delay):
        TimeSeries.objects.filter(platform=self.platform).update(constraints=CONSTRAINTS)
        with cassette():
            sync = plan_sync(self.platform)
        group = sync.groups[0]
        station = next(choice for choice in sync.fields if choice.name == "station_name")

        with cassette():
            response = self.client.post(
                self.url,
                {
                    "step": "apply",
                    "update": [f"{group.id}:dominant_wave_period"],
                    "field__station_name": station.options[0].id,
                    "location": "",
                },
            )

        self.assertRedirects(
            response,
            reverse("admin:deployments_platform_change", args=[self.platform.pk]),
            fetch_redirect_response=False,
        )
        constraints = dict(
            TimeSeries.objects.filter(platform=self.platform).values_list("variable", "constraints"),
        )
        self.assertEqual(
            constraints["dominant_wave_period"],
            {"depth=": 0.0, "dominant_wave_period_qc=": 0},
        )
        self.assertEqual(constraints["significant_wave_height"], CONSTRAINTS)
        self.platform.refresh_from_db()
        self.assertEqual(self.platform.station_name, "M01 Jordan Basin Accelerometer")
        mock_delay.assert_called_once()

    def test_requires_permissions(self):
        staff = get_user_model().objects.create_user("staff", password="pw", is_staff=True)
        self.client.force_login(staff)

        self.assertEqual(self.client.get(self.url).status_code, 403)
