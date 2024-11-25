import logging
import os
from collections.abc import Iterable
from datetime import timedelta

import requests
from celery import shared_task
from django.utils import timezone

from deployments.models import ErddapDataset

from .refresh import single_refresh_dataset

NOT_RECENTLY = timedelta(minutes=45)


logger = logging.getLogger(__name__)


@shared_task
def hourly_default_dataset_refresh():
    """Attempt to refresh any datasets that haven't been refreshed in the last hour."""
    healthcheck_url = os.environ.get("HOURLY_REFRESH_HEALTHCHECK_URL")

    if healthcheck_url:
        try:
            requests.get(healthcheck_url + "/start", timeout=5)
        except requests.RequestException as error:
            logger.error(
                f"Unable to send healthcheck start for hourly refresh due to: {error}",
                exc_info=True,
            )

    old_dataset_ids = not_recently_refreshed_datasets(NOT_RECENTLY)
    for dataset_id in old_dataset_ids:
        single_refresh_dataset.delay(dataset_id, healthcheck=True)
    logger.info(f"Launched dataset refreshes for {old_dataset_ids}")

    if healthcheck_url:
        try:
            requests.get(healthcheck_url, timeout=5)
        except requests.RequestException as error:
            logger.error(
                f"Unable to send healthcheck completion for hourly refresh due to error: {error}",
                exc_info=True,
            )


def not_recently_refreshed_datasets(time_before: timedelta) -> Iterable[int]:
    """Return the ids of datasets that have not been recently refreshed"""
    older_than = timezone.now() - time_before

    old_datasets = ErddapDataset.objects.filter(
        refresh_attempted__lt=older_than,
    ) | ErddapDataset.objects.filter(refresh_attempted__isnull=True)

    return [dataset.id for dataset in old_datasets]
