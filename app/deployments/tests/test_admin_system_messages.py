"""Tests for the SystemMessage admin surfaces: the sidebar, the containment gate and the badge.

The containment rule is the piece worth guarding hardest. Acknowledging a message is a global
act, so whether a page may offer an inline Acknowledge button depends on how far the message
reaches beyond that page -- and the reach of a message can change without the message row
itself changing at all (a second platform gaining a timeseries on the dataset is enough). The
regression that would otherwise slip through is exactly that: a dataset message that was
safely dismissable yesterday must stop being dismissable today.
"""

from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
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
class PromqlCopyAffordanceTestCase(SystemMessageAdminTestCase):
    """The sidebar's PromQL block: a copy button, click-to-select-all, and no side scroll.

    `self.timeseries` sits on `self.dataset`, and `_message`'s default code (`NOT_FOUND`) is
    an outcome code, so a message on either subject resolves to a query via
    `_promql_context` filling in the dataset name. A message on the platform itself never
    gets a dataset or server into that context, so it is the case with no query at all.
    """

    def test_the_script_delegates_because_it_loads_before_the_sidebar(self):
        """Django's Media puts this in <head> with no `defer`, so it runs before the sidebar.

        A version that bound listeners by querying `.system-message-promql` on load would find
        nothing and leave every button inert -- while the page still returned 200 and every
        other test in this class still passed, because they only assert the markup is present.
        There is no JS test harness in this repo, so this asserts the two halves of that
        contract directly: the script really does load ahead of the DOM it operates on, and it
        really does delegate from `document` rather than querying for the blocks up front.
        """
        _message(self.timeseries, message="Timeseries rung")

        html = self.platform_page().content.decode()
        script_at = html.find("deployments/js/system_messages.js")
        self.assertGreater(script_at, 0, "the script is not loaded at all")
        self.assertLess(script_at, html.find("</head>"), "script moved out of <head>")
        self.assertNotIn("defer", html[script_at - 120 : script_at])

        source = (
            Path(settings.BASE_DIR) / "deployments/static/deployments/js/system_messages.js"
        ).read_text()
        self.assertIn('document.addEventListener("click"', source)
        self.assertNotIn("document.querySelectorAll", source)

    def test_copy_control_and_query_text_render_for_a_message_with_a_query(self):
        _message(self.timeseries, message="Timeseries rung")

        response = self.platform_page()

        self.assertContains(response, "system-message-promql")
        self.assertContains(response, "system-message-copy")
        self.assertContains(response, "buoybarn_erddap_outcome_total")
        self.assertContains(response, self.dataset.name)

    def test_no_promql_block_or_button_when_the_message_has_no_query(self):
        _message(self.platform, message="Platform rung, no subject to key a query on")

        response = self.platform_page()

        self.assertContains(response, "Platform rung, no subject to key a query on")
        self.assertNotContains(response, "system-message-promql")
        self.assertNotContains(response, "system-message-copy")

    def test_query_text_stays_escaped(self):
        """Dataset names come from ERDDAP and are untrusted, same as message text.

        Deliberately given no timeseries of its own and read back from the SystemMessage
        change page (rather than a platform page), so this only exercises the PromQL
        rendering this ticket touches -- a dataset with a timeseries also feeds an unrelated,
        pre-existing unescaped-URL widget on the platform/dataset inline pages, which would
        make this test fail for a reason that has nothing to do with the copy affordance.
        """
        hostile_dataset = ErddapDataset.objects.create(
            name='M01"><script>alert(1)</script>',
            server=self.server,
        )
        message = _message(hostile_dataset)

        response = self.client.get(
            reverse("admin:deployments_systemmessage_change", args=[message.pk]),
        )

        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_static_js_is_referenced_on_the_change_page(self):
        _message(self.timeseries)

        response = self.platform_page()

        self.assertContains(response, "deployments/js/system_messages.js")


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
class SystemMessageListFilterTestCase(SystemMessageAdminTestCase):
    """The changelist filter and the sidebar have to agree, rung for rung.

    Each platform below is reachable through exactly one rung of the chain, and each sits on
    its own server, so a lookup that quietly collapses the chain -- or leaks a server's
    message onto every platform that shares it -- shows up as a name in the wrong bucket
    rather than as a subtly wrong count.
    """

    def platform_with_chain(self, name, level=None, subject_rung=None):
        """A platform with a server, dataset and timeseries all its own."""
        platform = Platform.objects.create(name=name, mooring_site_desc=name)
        server = ErddapServer.objects.create(name=f"{name}-server", base_url=f"http://{name}.test")
        dataset = ErddapDataset.objects.create(name=f"{name}_all", server=server)
        timeseries = TimeSeries.objects.create(
            platform=platform,
            data_type=self.water_temp,
            variable="temperature",
            depth=1,
            dataset=dataset,
        )
        rungs = {
            "platform": platform,
            "timeseries": timeseries,
            "dataset": dataset,
            "server": server,
        }
        if subject_rung is not None:
            _message(rungs[subject_rung], level=level)
        return rungs

    def setUp(self):
        super().setUp()
        self.own = self.platform_with_chain(
            "OWN",
            level=SystemMessage.Level.WARNING,
            subject_rung="platform",
        )
        self.via_dataset = self.platform_with_chain(
            "VIADATASET",
            level=SystemMessage.Level.INFO,
            subject_rung="dataset",
        )
        self.via_server = self.platform_with_chain(
            "VIASERVER",
            level=SystemMessage.Level.DANGER,
            subject_rung="server",
        )
        self.quiet = self.platform_with_chain("QUIET")

    def changelist(self, model_name="platform", **params):
        response = self.client.get(
            reverse(f"admin:deployments_{model_name}_changelist"),
            params,
        )
        self.assertEqual(response.status_code, 200)
        return response

    def names(self, **params):
        return [obj.name for obj in self.changelist(**params).context["cl"].result_list]

    def matched(self, value):
        """The names this lookup matches, restricted to the four platforms under test."""
        under_test = {"OWN", "VIADATASET", "VIASERVER", "QUIET"}
        return {name for name in self.names(system_message=value) if name in under_test}

    def test_any_matches_every_rung_of_the_chain(self):
        self.assertEqual(self.matched("any"), {"OWN", "VIADATASET", "VIASERVER"})

    def test_each_level_matches_only_its_own_platform(self):
        self.assertEqual(self.matched("warning"), {"OWN"})
        self.assertEqual(self.matched("info"), {"VIADATASET"})
        self.assertEqual(self.matched("danger"), {"VIASERVER"})

    def test_acknowledged_message_stops_matching_until_it_recurs(self):
        message = SystemMessage.objects.get(object_id=self.own["platform"].pk, level="warning")
        message.acknowledged_at = timezone.now()
        message.save(update_fields=["acknowledged_at"])

        self.assertNotIn("OWN", self.matched("any"))

        # The recurrence rule the whole feature rests on: the same row seen again after it
        # was acknowledged is outstanding again.
        message.last_seen = message.acknowledged_at + timedelta(minutes=1)
        message.save(update_fields=["last_seen"])

        self.assertIn("OWN", self.matched("any"))

    def test_resolved_message_does_not_match(self):
        SystemMessage.objects.filter(object_id=self.via_server["server"].pk).update(
            resolved_at=timezone.now(),
        )

        self.assertNotIn("VIASERVER", self.matched("any"))
        self.assertIn("VIASERVER", self.matched("none"))

    def test_none_means_nothing_anywhere_in_the_chain(self):
        none = self.matched("none")

        self.assertEqual(none, {"QUIET"})
        self.assertNotIn("VIASERVER", none)

    def test_none_includes_platforms_with_no_chain_at_all(self):
        self.assertIn("EXRX", self.names(system_message="none"))

    def test_a_platform_matched_on_several_rungs_appears_once(self):
        """The duplicate-row bug: joining through a multi-valued relation multiplies rows."""
        for rung, code in (
            ("timeseries", SystemMessage.Code.FORBIDDEN),
            ("dataset", SystemMessage.Code.SERVER_ERROR),
            ("server", SystemMessage.Code.UNKNOWN_ERROR),
        ):
            _message(self.own[rung], code=code, level=SystemMessage.Level.WARNING)

        names = self.names(system_message="any")

        self.assertEqual(names.count("OWN"), 1)

    def test_unfiltered_changelist_has_no_duplicates_either(self):
        names = self.names()

        self.assertEqual(len(names), len(set(names)))

    def order_index(self):
        """The `?o=` column index, taken from the changelist so the action column is counted."""
        changelist = self.changelist().context["cl"]
        return list(changelist.list_display).index(system_message_status)

    def ranked_names(self, descending=False):
        prefix = "-" if descending else ""
        names = self.names(o=f"{prefix}{self.order_index()}")
        return {name: position for position, name in enumerate(names)}

    def test_ordering_is_by_severity_not_alphabet(self):
        """`Level` sorts danger < info < warning as text, which is not severity order."""
        ascending = self.ranked_names()

        self.assertLess(ascending["QUIET"], ascending["VIADATASET"])
        self.assertLess(ascending["VIADATASET"], ascending["OWN"])
        self.assertLess(ascending["OWN"], ascending["VIASERVER"])

    def test_ordering_reverses(self):
        descending = self.ranked_names(descending=True)

        self.assertLess(descending["VIASERVER"], descending["OWN"])
        self.assertLess(descending["OWN"], descending["VIADATASET"])
        self.assertLess(descending["VIADATASET"], descending["QUIET"])

    def test_ordering_is_stable_between_requests(self):
        self.assertEqual(self.names(o=str(self.order_index())), self.names(o=str(self.order_index())))

    def test_query_count_does_not_grow_with_rows(self):
        def count(**params):
            with CaptureQueriesContext(connection) as queries:
                self.changelist(**params)
            return len(queries.captured_queries)

        few = count(system_message="any", o=f"-{self.order_index()}")

        for index in range(12):
            self.platform_with_chain(
                f"EXTRA{index}",
                level=SystemMessage.Level.DANGER,
                subject_rung="dataset",
            )

        many = count(system_message="any", o=f"-{self.order_index()}")

        self.assertEqual(many, few)

    def test_filter_actually_narrows_the_page(self):
        self.assertGreater(len(self.names()), len(self.names(system_message="any")))

    def test_timeseries_changelist_uses_its_own_chain(self):
        """A timeseries gathers its dataset and server -- but never its platform."""
        response = self.changelist("timeseries", system_message="danger")
        matched = {ts.pk for ts in response.context["cl"].result_list}

        self.assertIn(self.via_server["timeseries"].pk, matched)
        self.assertNotIn(self.own["timeseries"].pk, matched)
        self.assertNotIn(self.quiet["timeseries"].pk, matched)

    def test_timeseries_changelist_none_excludes_the_server_rung(self):
        response = self.changelist("timeseries", system_message="none")
        matched = {ts.pk for ts in response.context["cl"].result_list}

        self.assertNotIn(self.via_server["timeseries"].pk, matched)
        self.assertIn(self.quiet["timeseries"].pk, matched)
        # The platform's own message is off the timeseries chain, so it stays "none" here.
        self.assertIn(self.own["timeseries"].pk, matched)

    def test_dataset_changelist_gathers_its_server_and_timeseries(self):
        _message(
            self.quiet["timeseries"],
            code=SystemMessage.Code.FORBIDDEN,
            level=SystemMessage.Level.DANGER,
        )

        response = self.changelist("erddapdataset", system_message="danger")
        matched = {dataset.pk for dataset in response.context["cl"].result_list}

        self.assertIn(self.via_server["dataset"].pk, matched)
        self.assertIn(self.quiet["dataset"].pk, matched)
        self.assertNotIn(self.own["dataset"].pk, matched)

    def test_dataset_changelist_ignores_the_platform_rung(self):
        response = self.changelist("erddapdataset", system_message="none")
        matched = {dataset.pk for dataset in response.context["cl"].result_list}

        self.assertIn(self.own["dataset"].pk, matched)


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
