from collections.abc import Iterable
from datetime import timedelta

import django
import prefect
from django.utils import timezone
from prefect import task
from prefect.artifacts import create_markdown

django.setup()

from deployments.models import ErddapDataset  # noqa: E402
from deployments.tasks import refresh_dataset as refresh_dataset_base  # noqa: E402


@task
def not_recently_refreshed_datasets(time_before: timedelta) -> Iterable[int]:
    """Return the ids of datasets that have not been recently refreshed"""
    older_than = timezone.now() - time_before

    old_datasets = ErddapDataset.objects.filter(
        refresh_attempted__lt=older_than,
    ) | ErddapDataset.objects.filter(refresh_attempted__isnull=True)

    return [dataset.id for dataset in old_datasets]


@task
def refresh_dataset(dataset_id: int) -> int:
    """Run refresh any active timeseries for the dataset"""
    logger = prefect.context.get("logger")
    logger.info(f"Refreshing dataset {dataset_id}")

    refresh_dataset_base(dataset_id, healthcheck=True)

    logger.info(f"Finished refreshing dataset {dataset_id}")
    return dataset_id


@task
def refreshed_datasets_status(dataset_ids: Iterable[int]):
    """Creates an artifact with the datasets that were refreshed on the hour"""
    logger = prefect.context.get("logger")

    refreshed_datasets = (
        ErddapDataset.objects.select_related("server")
        .filter(id__in=dataset_ids)
        .order_by("server__name", "name")
    )

    markdown = "# Datasets refreshed on the hour \n\n"

    for dataset in refreshed_datasets:
        markdown += f"- {dataset}\n"

    logger.info(markdown)
    create_markdown(markdown)
