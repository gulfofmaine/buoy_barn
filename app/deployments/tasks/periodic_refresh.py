import logging
import os
from collections.abc import Iterable
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from deployments.models import ErddapDataset
from deployments.utils.healthchecks import ping_healthcheck

from .refresh import single_refresh_dataset

NOT_RECENTLY = timedelta(minutes=45)

#: Metric label for the hourly monitor. A short constant rather than the URL, which would
#: be both high cardinality and a secret.
HOURLY_REFRESH_MONITOR = "hourly_refresh"


logger = logging.getLogger(__name__)


@shared_task
def hourly_default_dataset_refresh():
    """Attempt to refresh any datasets that haven't been refreshed in the last hour."""
    healthcheck_url = os.environ.get("HOURLY_REFRESH_HEALTHCHECK_URL")

    # This ping is also how "did beat actually tick?" is monitored: configure the monitor
    # on the Healthchecks.io side with a `5 * * * *` schedule and a grace period, and a
    # missed tick alerts on absence. Without a schedule configured there, nothing alerts.
    ping_healthcheck(healthcheck_url, HOURLY_REFRESH_MONITOR, start=True)

    old_dataset_ids = not_recently_refreshed_datasets(NOT_RECENTLY)
    for dataset_id in old_dataset_ids:
        single_refresh_dataset.delay(dataset_id, healthcheck=True)
    logger.info(f"Launched dataset refreshes for {old_dataset_ids}")

    ping_healthcheck(healthcheck_url, HOURLY_REFRESH_MONITOR)


def not_recently_refreshed_datasets(time_before: timedelta) -> Iterable[int]:
    """Return the ids of datasets that have not been recently refreshed"""
    older_than = timezone.now() - time_before

    old_datasets = ErddapDataset.objects.filter(
        refresh_attempted__lt=older_than,
    ) | ErddapDataset.objects.filter(refresh_attempted__isnull=True)

    return [dataset.id for dataset in old_datasets]
