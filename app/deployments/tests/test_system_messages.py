from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from deployments.models import (
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    SystemMessage,
    TimeSeries,
)
from deployments.tasks.error_handling import Outcome, handle_500_time_range_error
from deployments.utils.system_messages import record_system_message, resolve_system_messages


@pytest.mark.django_db
class SystemMessageTestCase(TestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap_server = ErddapServer.objects.get(base_url="http://www.neracoos.org/erddap")
        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")

        self.dataset = ErddapDataset.objects.create(
            name="M01_sbe37_all",
            server=self.erddap_server,
        )
        self.timeseries = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.salinity,
            variable="salinity",
            depth=1,
            dataset=self.dataset,
        )

    def test_attached_to_platform_resolves_subject(self):
        message = SystemMessage.objects.create(
            subject=self.platform,
            code=SystemMessage.Code.NOT_FOUND,
            level=SystemMessage.Level.WARNING,
            message="Dataset not found",
        )

        fetched = SystemMessage.objects.get(pk=message.pk)
        self.assertEqual(fetched.subject, self.platform)

    def test_attached_to_timeseries_resolves_subject(self):
        message = SystemMessage.objects.create(
            subject=self.timeseries,
            code=SystemMessage.Code.END_TIME_RETIRED,
            level=SystemMessage.Level.INFO,
            message="End time retired",
        )

        fetched = SystemMessage.objects.get(pk=message.pk)
        self.assertEqual(fetched.subject, self.timeseries)

    def test_str(self):
        message = SystemMessage.objects.create(
            subject=self.platform,
            code=SystemMessage.Code.NOT_FOUND,
            level=SystemMessage.Level.WARNING,
            message="Dataset not found",
        )

        self.assertIn("Warning", str(message))
        self.assertIn(SystemMessage.Code.NOT_FOUND, str(message))
        self.assertIn(str(self.platform), str(message))

    def test_duplicate_subject_code_constraint_group_raises(self):
        SystemMessage.objects.create(
            subject=self.platform,
            code=SystemMessage.Code.NOT_FOUND,
            level=SystemMessage.Level.WARNING,
            message="Dataset not found",
        )

        with self.assertRaises(IntegrityError):
            SystemMessage.objects.create(
                subject=self.platform,
                code=SystemMessage.Code.NOT_FOUND,
                level=SystemMessage.Level.WARNING,
                message="Dataset not found again",
            )

    def test_differing_constraint_group_is_allowed(self):
        SystemMessage.objects.create(
            subject=self.timeseries,
            code=SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
            constraint_group="ab12cd34",
            level=SystemMessage.Level.DANGER,
            message="Unrecognized constraint",
        )

        # Should not raise: differing constraint_group makes this a distinct row.
        SystemMessage.objects.create(
            subject=self.timeseries,
            code=SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
            constraint_group="ef56ab78",
            level=SystemMessage.Level.DANGER,
            message="Unrecognized constraint",
        )

        self.assertEqual(SystemMessage.objects.count(), 2)

    def test_outstanding_includes_fresh_message(self):
        message = SystemMessage.objects.create(
            subject=self.platform,
            code=SystemMessage.Code.NOT_FOUND,
            level=SystemMessage.Level.WARNING,
            message="Dataset not found",
        )

        self.assertIn(message, SystemMessage.objects.outstanding())

    def test_outstanding_excludes_acknowledged_after_last_seen(self):
        now = timezone.now()
        message = SystemMessage.objects.create(
            subject=self.platform,
            code=SystemMessage.Code.NOT_FOUND,
            level=SystemMessage.Level.WARNING,
            message="Dataset not found",
            last_seen=now,
        )
        message.acknowledged_at = now + timedelta(minutes=1)
        message.save()

        self.assertNotIn(message, SystemMessage.objects.outstanding())

    def test_outstanding_recurs_once_last_seen_passes_acknowledged_at(self):
        """The core recurrence rule: an acknowledged message must reappear once it recurs.

        Acknowledgement is global to the row (there is nowhere else to attach it, since a
        recurring problem reuses the same row rather than creating a new one). So the only
        way to tell "acknowledged and still quiet" from "acknowledged but happening again"
        is to compare acknowledged_at against last_seen.
        """
        now = timezone.now()
        message = SystemMessage.objects.create(
            subject=self.platform,
            code=SystemMessage.Code.NOT_FOUND,
            level=SystemMessage.Level.WARNING,
            message="Dataset not found",
            last_seen=now,
        )
        message.acknowledged_at = now + timedelta(minutes=1)
        message.save()

        self.assertNotIn(message, SystemMessage.objects.outstanding())

        # The problem recurs: last_seen moves past the acknowledgement.
        message.last_seen = message.acknowledged_at + timedelta(minutes=1)
        message.occurrences += 1
        message.save()

        self.assertIn(message, SystemMessage.objects.outstanding())

    def test_outstanding_excludes_resolved(self):
        message = SystemMessage.objects.create(
            subject=self.platform,
            code=SystemMessage.Code.NOT_FOUND,
            level=SystemMessage.Level.WARNING,
            message="Dataset not found",
            resolved_at=timezone.now(),
        )

        self.assertNotIn(message, SystemMessage.objects.outstanding())

    def test_for_objects_across_heterogeneous_types_in_one_query(self):
        platform_message = SystemMessage.objects.create(
            subject=self.platform,
            code=SystemMessage.Code.NOT_FOUND,
            level=SystemMessage.Level.WARNING,
            message="Platform message",
        )
        dataset_message = SystemMessage.objects.create(
            subject=self.dataset,
            code=SystemMessage.Code.SERVER_ERROR,
            level=SystemMessage.Level.DANGER,
            message="Dataset message",
        )
        timeseries_message = SystemMessage.objects.create(
            subject=self.timeseries,
            code=SystemMessage.Code.END_TIME_RETIRED,
            level=SystemMessage.Level.INFO,
            message="Timeseries message",
        )

        with self.assertNumQueries(1):
            results = list(
                SystemMessage.objects.for_objects([self.platform, self.dataset, self.timeseries]),
            )

        self.assertCountEqual(
            results,
            [platform_message, dataset_message, timeseries_message],
        )

    def test_for_objects_empty_input_returns_empty_without_querying(self):
        with self.assertNumQueries(0):
            results = list(SystemMessage.objects.for_objects([]))

        self.assertEqual(results, [])


@pytest.mark.django_db
class SystemMessageUtilsTestCase(TestCase):
    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap_server = ErddapServer.objects.get(base_url="http://www.neracoos.org/erddap")
        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")

        self.dataset = ErddapDataset.objects.create(
            name="M01_sbe37_all",
            server=self.erddap_server,
        )
        self.timeseries = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.salinity,
            variable="salinity",
            depth=1,
            dataset=self.dataset,
        )

    # -- record_system_message -------------------------------------------------------

    def test_record_creates_a_row_with_one_occurrence(self):
        message = record_system_message(
            self.platform,
            SystemMessage.Code.NOT_FOUND,
            "Dataset not found",
            level=SystemMessage.Level.WARNING,
        )

        self.assertIsNotNone(message)
        self.assertEqual(message.occurrences, 1)
        self.assertEqual(SystemMessage.objects.count(), 1)

    def test_record_twice_reuses_the_row_and_bumps_occurrences(self):
        with freeze_time("2024-01-01 00:00:00"):
            first = record_system_message(
                self.platform,
                SystemMessage.Code.NOT_FOUND,
                "Dataset not found",
                level=SystemMessage.Level.WARNING,
            )

        with freeze_time("2024-01-02 00:00:00"):
            second = record_system_message(
                self.platform,
                SystemMessage.Code.NOT_FOUND,
                "Dataset not found again",
                level=SystemMessage.Level.WARNING,
            )

        self.assertEqual(SystemMessage.objects.count(), 1)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.occurrences, 2)
        self.assertGreater(second.last_seen, first.last_seen)
        self.assertEqual(second.first_seen, first.first_seen)

    def test_record_twice_overwrites_message_and_context(self):
        record_system_message(
            self.platform,
            SystemMessage.Code.NOT_FOUND,
            "First message",
            level=SystemMessage.Level.WARNING,
            context={"attempt": 1},
        )
        second = record_system_message(
            self.platform,
            SystemMessage.Code.NOT_FOUND,
            "Second message",
            level=SystemMessage.Level.WARNING,
            context={"attempt": 2},
        )

        self.assertEqual(second.message, "Second message")
        self.assertEqual(second.context, {"attempt": 2})

    def test_recording_a_resolved_message_reopens_it(self):
        message = record_system_message(
            self.platform,
            SystemMessage.Code.NOT_FOUND,
            "Dataset not found",
            level=SystemMessage.Level.WARNING,
        )
        message.resolved_at = timezone.now()
        message.save()

        reopened = record_system_message(
            self.platform,
            SystemMessage.Code.NOT_FOUND,
            "Dataset not found again",
            level=SystemMessage.Level.WARNING,
        )

        self.assertIsNone(reopened.resolved_at)
        self.assertIn(reopened, SystemMessage.objects.outstanding())

    def test_record_with_differing_constraint_group_creates_separate_rows(self):
        record_system_message(
            self.timeseries,
            SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
            "Bad constraint",
            level=SystemMessage.Level.DANGER,
            constraint_group="ab12cd34",
        )
        record_system_message(
            self.timeseries,
            SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
            "Bad constraint",
            level=SystemMessage.Level.DANGER,
            constraint_group="ef56ab78",
        )

        self.assertEqual(SystemMessage.objects.count(), 2)

    def test_record_never_raises_when_the_write_fails(self):
        with patch.object(
            SystemMessage.objects,
            "update_or_create",
            side_effect=RuntimeError("boom"),
        ):
            result = record_system_message(
                self.platform,
                SystemMessage.Code.NOT_FOUND,
                "Dataset not found",
                level=SystemMessage.Level.WARNING,
            )

        self.assertIsNone(result)
        self.assertEqual(SystemMessage.objects.count(), 0)

    # -- resolve_system_messages ------------------------------------------------------

    def test_resolve_sets_resolved_at_and_returns_count(self):
        record_system_message(
            self.platform,
            SystemMessage.Code.NOT_FOUND,
            "Dataset not found",
            level=SystemMessage.Level.WARNING,
        )

        count = resolve_system_messages(self.platform, SystemMessage.Code.NOT_FOUND)

        self.assertEqual(count, 1)
        message = SystemMessage.objects.get(
            content_type__model="platform",
            object_id=self.platform.pk,
            code=SystemMessage.Code.NOT_FOUND,
        )
        self.assertIsNotNone(message.resolved_at)
        self.assertNotIn(message, SystemMessage.objects.outstanding())

    def test_resolve_leaves_other_codes_alone(self):
        record_system_message(
            self.platform,
            SystemMessage.Code.NOT_FOUND,
            "Dataset not found",
            level=SystemMessage.Level.WARNING,
        )
        record_system_message(
            self.platform,
            SystemMessage.Code.FORBIDDEN,
            "Forbidden",
            level=SystemMessage.Level.DANGER,
        )

        resolve_system_messages(self.platform, SystemMessage.Code.NOT_FOUND)

        still_outstanding = SystemMessage.objects.outstanding().get(
            code=SystemMessage.Code.FORBIDDEN,
        )
        self.assertIsNone(still_outstanding.resolved_at)

    def test_resolve_with_constraint_group_only_resolves_that_group(self):
        record_system_message(
            self.timeseries,
            SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
            "Bad constraint",
            level=SystemMessage.Level.DANGER,
            constraint_group="ab12cd34",
        )
        record_system_message(
            self.timeseries,
            SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
            "Bad constraint",
            level=SystemMessage.Level.DANGER,
            constraint_group="ef56ab78",
        )

        count = resolve_system_messages(
            self.timeseries,
            SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
            constraint_group="ab12cd34",
        )

        self.assertEqual(count, 1)
        resolved = SystemMessage.objects.get(constraint_group="ab12cd34")
        untouched = SystemMessage.objects.get(constraint_group="ef56ab78")
        self.assertIsNotNone(resolved.resolved_at)
        self.assertIsNone(untouched.resolved_at)

    def test_resolve_never_raises_when_the_write_fails(self):
        record_system_message(
            self.platform,
            SystemMessage.Code.NOT_FOUND,
            "Dataset not found",
            level=SystemMessage.Level.WARNING,
        )

        with patch(
            "deployments.utils.system_messages.ContentType.objects.get_for_model",
            side_effect=RuntimeError("boom"),
        ):
            count = resolve_system_messages(self.platform, SystemMessage.Code.NOT_FOUND)

        self.assertEqual(count, 0)


@pytest.mark.django_db
class Handle500TimeRangeErrorTestCase(TestCase):
    """`handle_500_time_range_error` is the origin of `end_time_retired` (issue #1855):

    writing `end_time` drops a timeseries out of `TimeSeriesQuerySet.refreshable()`, silently
    retiring a platform that is actually still live. These tests call the handler directly,
    the same way `deployments.tasks.refresh.update_values_for_timeseries` reaches it through
    `handle_http_errors` -> `handle_500_errors`, so the emitted SystemMessage and the
    unchanged return value can both be asserted without a network fixture.
    """

    fixtures = ["platforms", "erddapservers", "datatypes"]

    def setUp(self):
        self.platform = Platform.objects.get(name="M01")
        self.erddap_server = ErddapServer.objects.get(base_url="http://www.neracoos.org/erddap")
        self.salinity = DataType.objects.get(standard_name="sea_water_salinity")
        self.water_temp = DataType.objects.get(standard_name="sea_water_temperature")

        self.dataset = ErddapDataset.objects.create(
            name="M01_sbe37_all",
            server=self.erddap_server,
        )
        self.ts1 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.salinity,
            variable="salinity",
            constraints={"depth=": 100.0},
            start_time="2004-06-03 21:00:00+00",
            dataset=self.dataset,
        )
        self.ts2 = TimeSeries.objects.create(
            platform=self.platform,
            data_type=self.water_temp,
            variable="temperature",
            constraints={"depth=": 100.0},
            start_time="2004-06-03 21:00:00+00",
            dataset=self.dataset,
        )
        self.compare_text = (
            "Your query produced no matching results. (time&gt;=2020-10-04T19:40:20Z is "
            "outside of the variable's actual_range: 2018-07-17T17:00:00Z to "
            "2019-03-28T14:20:00Z)"
        )

    def test_retires_each_timeseries_and_records_a_danger_message(self):
        result = handle_500_time_range_error([self.ts1, self.ts2], self.compare_text)

        # Behaviour is unchanged: the handler still reports the outcome it always has.
        self.assertEqual(result, Outcome.TIME_RANGE_RETIRED)

        for ts in (self.ts1, self.ts2):
            ts.refresh_from_db()
            self.assertIsNotNone(ts.end_time)

            message = SystemMessage.objects.for_object(ts).get(
                code=SystemMessage.Code.END_TIME_RETIRED,
            )
            self.assertEqual(message.level, SystemMessage.Level.DANGER)
            self.assertIn(ts.end_time.isoformat(), message.message)
            self.assertEqual(message.context["end_time"], ts.end_time.isoformat())
            self.assertEqual(message.context["dataset"], self.dataset.name)

        # One message per retired timeseries, not one for the whole group.
        self.assertEqual(
            SystemMessage.objects.filter(code=SystemMessage.Code.END_TIME_RETIRED).count(),
            2,
        )
