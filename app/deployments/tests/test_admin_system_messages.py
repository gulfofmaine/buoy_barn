"""Tests for the SystemMessage admin surfaces: the sidebar, the containment gate and the badge.

The containment rule is the piece worth guarding hardest. Acknowledging a message is a global
act, so whether a page may offer an inline Acknowledge button depends on how far the message
reaches beyond that page -- and the reach of a message can change without the message row
itself changing at all (a second platform gaining a timeseries on the dataset is enough). The
regression that would otherwise slip through is exactly that: a dataset message that was
safely dismissable yesterday must stop being dismissable today.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from deployments.admin import (
    compute_message_reach,
    related_subjects,
    system_message_status,
)
from deployments.models import (
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    SystemMessage,
    TimeSeries,
)


def _message(subject, *, code=SystemMessage.Code.NOT_FOUND, level=SystemMessage.Level.DANGER, **kwargs):
    return SystemMessage.objects.create(
        subject=subject,
        code=code,
        level=level,
        message=kwargs.pop("message", "Something went wrong"),
        **kwargs,
    )


class SystemMessageAdminTestCase(TestCase):
    """Shared fixtures: one platform, one dataset with one timeseries, on one server."""

    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",  # noqa: S106
        )
        self.client.force_login(self.user)

        self.platform = Platform.objects.get(name="M01")
        self.server = ErddapServer.objects.get(base_url="http://www.neracoos.org/erddap")
        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")
        self.water_temp = DataType.objects.get(standard_name="sea_water_temperature")

        self.dataset = ErddapDataset.objects.create(name="M01_sbe37_all", server=self.server)
        self.timeseries = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.salinity,
            variable="salinity",
            depth=1,
            dataset=self.dataset,
        )

    def platform_page(self, platform=None):
        platform = platform or self.platform
        return self.client.get(
            reverse("admin:deployments_platform_change", args=[platform.pk]),
        )

    def rows(self, response):
        return response.context["system_messages"]

    def row_for(self, response, message):
        for row in self.rows(response):
            if row.message.pk == message.pk:
                return row
        raise AssertionError(f"{message!r} was not in the sidebar")


@pytest.mark.django_db
class PlatformSidebarGatheringTestCase(SystemMessageAdminTestCase):
    """Every rung of platform -> timeseries -> dataset -> server reaches the platform page."""

    def test_timeseries_message_appears(self):
        _message(self.timeseries, message="Timeseries rung")

        self.assertContains(self.platform_page(), "Timeseries rung")

    def test_dataset_message_appears(self):
        _message(self.dataset, message="Dataset rung")

        self.assertContains(self.platform_page(), "Dataset rung")

    def test_server_message_appears(self):
        _message(self.server, message="Server rung")

        self.assertContains(self.platform_page(), "Server rung")

    def test_platform_message_appears(self):
        _message(self.platform, message="Platform rung")

        self.assertContains(self.platform_page(), "Platform rung")

    def test_resolved_message_is_not_gathered(self):
        _message(self.timeseries, message="Old news", resolved_at=timezone.now())

        self.assertNotContains(self.platform_page(), "Old news")

    def test_subject_is_labelled_and_linked(self):
        message = _message(self.dataset, message="Dataset rung")

        row = self.row_for(self.platform_page(), message)

        self.assertIn("Dataset", row.subject_label)
        self.assertIn(str(self.dataset), row.subject_label)
        self.assertEqual(
            row.subject_url,
            reverse("admin:deployments_erddapdataset_change", args=[self.dataset.pk]),
        )

    def test_message_text_is_escaped(self):
        _message(self.timeseries, message="<script>alert('xss')</script>")

        response = self.platform_page()

        self.assertNotContains(response, "<script>alert(")
        self.assertContains(response, "&lt;script&gt;")

    def test_object_actions_survive_the_sidebar_template(self):
        """The sidebar template must extend django_object_actions', not admin's, change form."""
        response = self.platform_page()

        self.assertContains(response, "objectaction-item")
        self.assertContains(response, "refresh_platform_datasets")


@pytest.mark.django_db
class ContainmentGateTestCase(SystemMessageAdminTestCase):
    def second_platform_timeseries(self):
        """A timeseries on `self.dataset` belonging to a *different* platform."""
        other = Platform.objects.create(name="OTHER", mooring_site_desc="Somewhere else")
        return TimeSeries.objects.create(
            platform=other,
            data_type=self.water_temp,
            variable="temperature",
            depth=1,
            dataset=self.dataset,
        )

    def test_timeseries_message_is_dismissable_on_its_platform(self):
        message = _message(self.timeseries)

        row = self.row_for(self.platform_page(), message)

        self.assertTrue(row.can_acknowledge)
        self.assertEqual(row.spill_count, 0)

    def test_dataset_message_is_dismissable_when_the_dataset_is_this_platforms_alone(self):
        message = _message(self.dataset)

        row = self.row_for(self.platform_page(), message)

        self.assertTrue(row.can_acknowledge)
        self.assertEqual(row.spill_count, 0)

    def test_same_dataset_message_stops_being_dismissable_once_a_second_platform_joins(self):
        """Nothing about the message row changes -- only the dataset's reach does."""
        message = _message(self.dataset)
        self.assertTrue(self.row_for(self.platform_page(), message).can_acknowledge)

        self.second_platform_timeseries()

        row = self.row_for(self.platform_page(), message)
        self.assertFalse(row.can_acknowledge)
        self.assertEqual(row.spill_count, 1)
        self.assertEqual(row.reach_count, 2)
        self.assertEqual(row.reach_label, "platforms")

    def test_server_message_spanning_two_platforms_is_not_dismissable(self):
        other_platform = Platform.objects.create(name="OTHER", mooring_site_desc="Elsewhere")
        other_dataset = ErddapDataset.objects.create(name="B01_sbe37_all", server=self.server)
        TimeSeries.objects.create(
            platform=other_platform,
            data_type=self.water_temp,
            variable="temperature",
            depth=1,
            dataset=other_dataset,
        )
        message = _message(self.server)

        row = self.row_for(self.platform_page(), message)

        self.assertFalse(row.can_acknowledge)
        self.assertEqual(row.spill_count, 1)
        self.assertEqual(row.reach_count, 2)

    def test_platform_message_is_dismissable_on_its_own_page(self):
        message = _message(self.platform)

        row = self.row_for(self.platform_page(), message)

        self.assertTrue(row.can_acknowledge)

    def test_server_message_is_dismissable_on_the_dataset_page_when_it_reaches_one_dataset(self):
        """Containment is measured in datasets on a dataset page, not in platforms."""
        message = _message(self.server)

        response = self.client.get(
            reverse("admin:deployments_erddapdataset_change", args=[self.dataset.pk]),
        )

        row = self.row_for(response, message)
        self.assertTrue(row.can_acknowledge)

    def test_timeseries_page_gathers_its_dataset_and_server(self):
        """Exercises the plain-ModelAdmin change form, which has its own template."""
        dataset_message = _message(self.dataset, message="Dataset rung")
        _message(self.server, code=SystemMessage.Code.FORBIDDEN, message="Server rung")

        response = self.client.get(
            reverse("admin:deployments_timeseries_change", args=[self.timeseries.pk]),
        )

        self.assertContains(response, "Dataset rung")
        self.assertContains(response, "Server rung")
        # Containment on a timeseries page is measured in timeseries, and this dataset has
        # only the one.
        self.assertTrue(self.row_for(response, dataset_message).can_acknowledge)
        self.assertEqual(self.row_for(response, dataset_message).reach_label, "timeseries")

    def test_server_page_gathers_its_datasets(self):
        _message(self.dataset, message="Dataset rung")

        response = self.client.get(
            reverse("admin:deployments_erddapserver_change", args=[self.server.pk]),
        )

        self.assertContains(response, "Dataset rung")
        self.assertContains(response, "objectaction-item")

    def test_uncontained_row_offers_the_review_impact_link(self):
        self.second_platform_timeseries()
        message = _message(self.dataset)

        response = self.platform_page()

        self.assertContains(response, "Review impact")
        self.assertContains(
            response,
            reverse("admin:deployments_systemmessage_change", args=[message.pk]),
        )

    def test_contained_row_offers_an_acknowledge_form(self):
        message = _message(self.timeseries)

        response = self.platform_page()

        self.assertContains(
            response,
            reverse("admin:deployments_systemmessage_acknowledge", args=[message.pk]),
        )
        self.assertContains(response, "csrfmiddlewaretoken")


@pytest.mark.django_db
class ReachQueryCountTestCase(SystemMessageAdminTestCase):
    def make_messages(self, count, prefix):
        """`count` outstanding messages spread over the three non-platform subject types.

        `prefix` keeps two batches from colliding on the (subject, code, constraint_group)
        unique constraint.
        """
        subjects = [self.timeseries, self.dataset, self.server]
        codes = list(SystemMessage.Code)
        return [
            _message(
                subjects[index % len(subjects)],
                code=codes[index % len(codes)],
                constraint_group=f"{prefix}{index}",
            )
            for index in range(count)
        ]

    def reach_query_count(self, messages):
        with CaptureQueriesContext(connection) as queries:
            compute_message_reach(messages)
        return len(queries)

    def test_reach_is_a_constant_number_of_queries(self):
        """Same subject types, ten times as many messages, same number of queries.

        Reach is grouped by subject type, so the cost tracks the number of *types* present
        (at most four), never the number of messages. Both batches below cover the same three
        types so the only variable is how many messages there are.
        """
        few = self.make_messages(3, "a")
        many = self.make_messages(30, "b")

        self.assertEqual(self.reach_query_count(many), self.reach_query_count(few))

    def test_reach_of_an_empty_list_costs_nothing(self):
        self.assertEqual(self.reach_query_count([]), 0)


@pytest.mark.django_db
class AcknowledgeViewTestCase(SystemMessageAdminTestCase):
    def setUp(self):
        super().setUp()
        self.message = _message(self.timeseries)
        self.url = reverse(
            "admin:deployments_systemmessage_acknowledge",
            args=[self.message.pk],
        )
        self.platform_url = reverse(
            "admin:deployments_platform_change",
            args=[self.platform.pk],
        )

    def test_get_is_rejected(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)

    def test_staff_without_change_permission_is_rejected(self):
        peon = get_user_model().objects.create_user(
            username="peon",
            email="peon@example.com",
            password="password",  # noqa: S106
            is_staff=True,
        )
        self.client.force_login(peon)

        response = self.client.post(self.url, {"next": self.platform_url})

        self.assertEqual(response.status_code, 403)
        self.message.refresh_from_db()
        self.assertIsNone(self.message.acknowledged_at)

    def test_post_stamps_the_acknowledgement_and_redirects(self):
        response = self.client.post(self.url, {"next": self.platform_url})

        self.assertRedirects(response, self.platform_url)
        self.message.refresh_from_db()
        self.assertIsNotNone(self.message.acknowledged_at)
        self.assertEqual(self.message.acknowledged_by, self.user)

    def test_offsite_next_is_refused(self):
        response = self.client.post(self.url, {"next": "https://evil.example.com/"})

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("evil.example.com", response["Location"])
        self.assertEqual(
            response["Location"],
            reverse("admin:deployments_systemmessage_change", args=[self.message.pk]),
        )

    def test_missing_next_falls_back_to_the_message(self):
        response = self.client.post(self.url)

        self.assertEqual(
            response["Location"],
            reverse("admin:deployments_systemmessage_change", args=[self.message.pk]),
        )


@pytest.mark.django_db
class SystemMessageAdminActionsTestCase(SystemMessageAdminTestCase):
    def test_acknowledge_action_stamps_user_and_time(self):
        message = _message(self.timeseries)

        response = self.client.post(
            reverse("admin:deployments_systemmessage_changelist"),
            {
                "action": "acknowledge_messages",
                "_selected_action": [str(message.pk)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertIsNotNone(message.acknowledged_at)
        self.assertEqual(message.acknowledged_by, self.user)

    def test_unacknowledge_action_clears_the_stamp(self):
        message = _message(
            self.timeseries,
            acknowledged_at=timezone.now(),
            acknowledged_by=self.user,
        )

        self.client.post(
            reverse("admin:deployments_systemmessage_changelist"),
            {
                "action": "unacknowledge_messages",
                "_selected_action": [str(message.pk)],
            },
            follow=True,
        )

        message.refresh_from_db()
        self.assertIsNone(message.acknowledged_at)
        self.assertIsNone(message.acknowledged_by)

    def test_changelist_defaults_to_outstanding(self):
        _message(self.timeseries, message="Still a problem")
        _message(self.dataset, message="Long since fixed", resolved_at=timezone.now())

        response = self.client.get(reverse("admin:deployments_systemmessage_changelist"))

        self.assertContains(response, "Still a problem")
        self.assertNotContains(response, "Long since fixed")

    def test_messages_cannot_be_added(self):
        response = self.client.get(reverse("admin:deployments_systemmessage_add"))

        self.assertEqual(response.status_code, 403)

    def test_change_page_lists_the_impact(self):
        message = _message(self.server)

        response = self.client.get(
            reverse("admin:deployments_systemmessage_change", args=[message.pk]),
        )

        self.assertContains(response, str(self.platform))
        self.assertContains(
            response,
            reverse("admin:deployments_platform_change", args=[self.platform.pk]),
        )
        self.assertContains(
            response,
            reverse("admin:deployments_erddapdataset_change", args=[self.dataset.pk]),
        )

    def test_message_body_is_readonly(self):
        message = _message(self.timeseries)

        response = self.client.get(
            reverse("admin:deployments_systemmessage_change", args=[message.pk]),
        )

        self.assertNotContains(response, 'name="message"')
        # A split datetime widget, so the editable acknowledgement shows up as _0/_1.
        self.assertContains(response, 'name="acknowledged_at_0"')
        self.assertContains(response, 'name="acknowledged_by"')


@pytest.mark.django_db
class SplitBadgeTestCase(SystemMessageAdminTestCase):
    def test_badge_separates_contained_from_spilling(self):
        other_platform = Platform.objects.create(name="OTHER", mooring_site_desc="Elsewhere")
        other_dataset = ErddapDataset.objects.create(name="B01_sbe37_all", server=self.server)
        TimeSeries.objects.create(
            platform=other_platform,
            data_type=self.water_temp,
            variable="temperature",
            depth=1,
            dataset=other_dataset,
        )
        _message(self.timeseries, level=SystemMessage.Level.DANGER)
        _message(
            self.dataset,
            code=SystemMessage.Code.FORBIDDEN,
            level=SystemMessage.Level.DANGER,
        )
        _message(self.server, code=SystemMessage.Code.SERVER_ERROR)

        badge = system_message_status(self.platform)

        self.assertIn("2 danger", badge)
        self.assertIn("+1 server", badge)

    def test_badge_is_quiet_when_there_is_nothing_to_say(self):
        badge = system_message_status(self.platform)

        self.assertIn("None", badge)

    def test_badge_is_computed_once_per_changelist_page(self):
        for index in range(3):
            platform = Platform.objects.create(
                name=f"P{index}",
                mooring_site_desc="A platform",
            )
            timeseries = TimeSeries.objects.create(
                platform=platform,
                data_type=self.water_temp,
                variable="temperature",
                depth=index,
                dataset=self.dataset,
            )
            _message(timeseries)

        with CaptureQueriesContext(connection) as few:
            self.client.get(reverse("admin:deployments_platform_changelist"))

        for index in range(3, 9):
            platform = Platform.objects.create(
                name=f"P{index}",
                mooring_site_desc="A platform",
            )
            timeseries = TimeSeries.objects.create(
                platform=platform,
                data_type=self.water_temp,
                variable="temperature",
                depth=index,
                dataset=self.dataset,
            )
            _message(timeseries)

        with CaptureQueriesContext(connection) as many:
            self.client.get(reverse("admin:deployments_platform_changelist"))

        self.assertEqual(len(many.captured_queries), len(few.captured_queries))


@pytest.mark.django_db
class RelatedSubjectsTestCase(SystemMessageAdminTestCase):
    def test_platform_gathers_the_whole_chain(self):
        subjects = related_subjects(self.platform)

        self.assertIn(self.platform, subjects)
        self.assertIn(self.timeseries, subjects)
        self.assertIn(self.dataset, subjects)
        self.assertIn(self.server, subjects)

    def test_dataset_gathers_itself_its_server_and_its_timeseries(self):
        subjects = related_subjects(self.dataset)

        self.assertCountEqual(subjects, [self.dataset, self.server, self.timeseries])

    def test_server_gathers_itself_and_its_datasets(self):
        subjects = related_subjects(self.server)

        self.assertCountEqual(subjects, [self.server, self.dataset])

    def test_timeseries_gathers_itself_its_dataset_and_its_server(self):
        subjects = related_subjects(self.timeseries)

        self.assertCountEqual(subjects, [self.timeseries, self.dataset, self.server])


@pytest.mark.django_db
class MessageReachTestCase(SystemMessageAdminTestCase):
    def test_dataset_message_reaches_every_platform_on_the_dataset(self):
        other = Platform.objects.create(name="OTHER", mooring_site_desc="Elsewhere")
        TimeSeries.objects.create(
            platform=other,
            data_type=self.water_temp,
            variable="temperature",
            depth=1,
            dataset=self.dataset,
        )
        message = _message(self.dataset)

        reach = compute_message_reach([message])[message.pk]

        self.assertEqual(reach.platform_ids, frozenset({self.platform.pk, other.pk}))
        self.assertEqual(reach.dataset_ids, frozenset({self.dataset.pk}))

    def test_subject_is_always_in_its_own_axis(self):
        empty_dataset = ErddapDataset.objects.create(name="empty", server=self.server)
        message = _message(empty_dataset)

        reach = compute_message_reach([message])[message.pk]

        self.assertEqual(reach.dataset_ids, frozenset({empty_dataset.pk}))
        self.assertEqual(reach.platform_ids, frozenset())

    def test_unknown_subject_type_reaches_nothing(self):
        message = SystemMessage.objects.create(
            content_type=ContentType.objects.get_for_model(DataType),
            object_id=self.salinity.pk,
            code=SystemMessage.Code.UNKNOWN_ERROR,
            level=SystemMessage.Level.INFO,
            message="Nothing to reach",
        )

        reach = compute_message_reach([message])[message.pk]

        self.assertEqual(reach.platform_ids, frozenset())
