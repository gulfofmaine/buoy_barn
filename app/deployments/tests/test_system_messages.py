from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from deployments.models import (
    DataType,
    ErddapDataset,
    ErddapServer,
    Platform,
    SystemMessage,
    TimeSeries,
)


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
                SystemMessage.objects.for_objects([self.platform, self.dataset, self.timeseries])
            )

        self.assertCountEqual(
            results,
            [platform_message, dataset_message, timeseries_message],
        )

    def test_for_objects_empty_input_returns_empty_without_querying(self):
        with self.assertNumQueries(0):
            results = list(SystemMessage.objects.for_objects([]))

        self.assertEqual(results, [])
