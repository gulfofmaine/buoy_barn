from collections import defaultdict
from collections.abc import Iterable
from typing import Union

import django
import prefect
from prefect import Flow, task
from prefect.artifacts import create_markdown
from prefect.storage.local import Local
from requests import HTTPError

# Needs to be called before any models can be imported
django.setup()

from deployments.models import TimeSeries  # noqa: E402
from deployments.utils.erddap_datasets import retrieve_dataframe  # noqa: E402

TimeSeriesGroup = tuple[
    tuple[str, Iterable[tuple[str, Union[str, int, float]]]],
    Iterable[int],
]


@task
def find_outdated_timeseries() -> Iterable[TimeSeriesGroup]:
    """Return timeseries with an end_time set"""

    logger = prefect.context.get("logger")
    groups = defaultdict(list)

    logger.info("Finding TimeSeries with `end_time` set.")

    for ts in TimeSeries.objects.exclude(end_time__isnull=True):
        try:
            groups[(ts.dataset.name, tuple((ts.constraints or {}).items()))].append(
                ts.id,
            )
        except AttributeError as e:
            logger.error(f"Unable to set constraint for timeseries {ts} due to {e}")

    ts_groups = list(groups.items())
    logger.info(f"There are {len(ts_groups)} groups of outdated TimeSeries")
    return ts_groups


TimeseriesUpdated = tuple[Iterable[int], bool]


@task
def check_timeseries_for_updates(ts_group: TimeSeriesGroup) -> TimeseriesUpdated:
    """Check to see if an outdated timeseries group is now updated"""

    logger = prefect.context.get("logger")

    (dataset, constraint), timeseries_ids = ts_group

    timeseries = TimeSeries.objects.filter(id__in=timeseries_ids)

    try:
        retrieve_dataframe(
            timeseries[0].dataset.server,
            timeseries[0].dataset.name,
            timeseries[0].constraints,
            timeseries,
        )
    except HTTPError:
        logger.info(
            f"Dataset {dataset} with constraint {constraint} has not been updated",
        )
        return tuple(timeseries_ids), False
    else:
        logger.info(f"Dataset {dataset} with constraint {constraint} has been updated")

        for ts in timeseries:
            ts.end_time = None
            ts.save()

        logger.info(f"`end_time` reset on {len(timeseries)} TimeSeries")

        return tuple(timeseries_ids), True


@task
def log_timeseries_status(ts_status: Iterable[TimeseriesUpdated]):
    """Generate an artifact with the status of timeseries"""
    logger = prefect.context.get("logger")

    updated: list[int] = []
    not_updated: list[int] = []

    for timeseries_ids, was_updated in ts_status:
        if was_updated:
            updated += timeseries_ids
        else:
            not_updated += timeseries_ids

    markdown = """
# Checked for restarted TimeSeries

TimeSeries with `end_time` were checked to see if they have been updated.

    """

    if updated:
        markdown += "## Restarted TimeSeries \n"
        markdown += platforms_timeseries_markdown(updated)
        markdown += "\n"

    if not_updated:
        markdown += "## TimeSeries that have not been restarted \n"
        markdown += platforms_timeseries_markdown(not_updated)

    logger.info(markdown)
    create_markdown(markdown)


def platforms_timeseries_markdown(timeseries_ids: Iterable[int]) -> str:
    """Return a markdown formatted block with the platforms and timeseries"""

    platforms = defaultdict(list)

    for ts in TimeSeries.objects.filter(id__in=timeseries_ids):
        platforms[ts.platform.name].append(
            (ts.dataset.server.name, ts.dataset.name, ts.variable, ts.depth),
        )

    markdown = "\n"

    for platform, timeseries in platforms.items():
        markdown += f"- {platform}\n"

        for server, dataset, variable, depth in timeseries:
            markdown += f"  - {server} - {dataset} - {variable} @ {depth}\n"

    return markdown


with Flow("reset_timeseries_end_times") as flow:
    outdated_timeseries = find_outdated_timeseries()
    timeseries_updated = check_timeseries_for_updates.map(outdated_timeseries)
    log_timeseries_status(timeseries_updated)


# flow should be stored as script so that `django.setup()` gets called appropriately
flow.storage = Local(
    path="deployments.flows.reset_timeseries_end_times",
    stored_as_script=True,
)
