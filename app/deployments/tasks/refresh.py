import logging
import time

import pandas as pd
from celery import shared_task
from django.utils import timezone
from httpcore import ConnectError
from httpx import HTTPError, TimeoutException

# from requests import HTTPError, Timeout
from sentry_sdk import push_scope

from deployments.models import ErddapDataset, ErddapServer, TimeSeries
from deployments.utils.erddap_datasets import (
    TIME_COLUMN,
    VALUE_COLUMN,
    filter_dataframe,
    retrieve_dataframe,
)

from .error_handling import BackoffError, handle_http_errors
from .extrema import extrema_for_timeseries
from .queue import task_queued

logger = logging.getLogger(__name__)


def update_values_for_timeseries(timeseries: list[TimeSeries]):
    """Update values and most recent times for a group of timeseries that have the same constraints"""
    with push_scope() as scope:
        scope.set_tag("erddap-server", timeseries[0].dataset.server)
        scope.set_tag("erddap-dataset", timeseries[0].dataset.name)

        logger.info(f"Working on timeseries: {timeseries}")
        try:
            timeseries_df = retrieve_dataframe(
                timeseries[0].dataset.server,
                timeseries[0].dataset.name,
                timeseries[0].constraints,
                timeseries,
            )

        except (ConnectError, TimeoutException) as error:
            raise BackoffError(
                f"Timeout when trying to retrieve dataset {timeseries[0].dataset.name} "
                f"with constraint {timeseries[0].constraints}: {error}",
            ) from error

        except HTTPError as error:
            if handle_http_errors(timeseries, error):
                return

        except OSError as error:
            logger.error(
                (
                    f"Error loading dataset {timeseries[0].dataset.name} with "
                    f"constraints {timeseries[0].constraints}: {error}"
                ),
                extra={
                    "timeseries": timeseries,
                    "constraints": timeseries[0].constraints,
                },
                exc_info=True,
            )
            return

        for series in timeseries:
            filtered_df = filter_dataframe(timeseries_df, series.variable)

            extra_context = {
                "timeseries": timeseries,
                "constraints": timeseries[0].constraints,
            }

            try:
                if series.timeseries_type in TimeSeries.FUTURE_TYPES:
                    row = filtered_df.iloc[1]
                else:
                    row = filtered_df.iloc[-1]
                extra_context["row"] = row
            except IndexError:
                msg = (
                    f"Unable to find position in dataframe for {series.platform.name} - "
                    f"{series.variable}"
                )
                logger.warning(
                    msg,
                    #    extra=extra_context,
                    #    exc_info=True
                )
                continue

            try:
                value = row[VALUE_COLUMN]

                extra_context["series"] = series
                extra_context["variable"] = series.variable
                extra_context[VALUE_COLUMN] = value

                if isinstance(value, pd.Timedelta):
                    logger.info("Converting from Timedelta to seconds")
                    value = value.seconds

                series.value = value

                time = row[TIME_COLUMN]
                extra_context["time"] = time

                series.value_time = pd.to_datetime(time)
                series.save()

                try:
                    series.extrema_values = extrema_for_timeseries(series, filtered_df)
                    series.save()
                except TypeError as error:
                    logger.error(
                        f"Could not save extrema for {series.variable} from {row}: {error}",
                        extra=extra_context,
                        exc_info=True,
                    )
                    continue
            except (TypeError, ValueError) as error:
                logger.error(
                    f"Could not save {series.variable} from {row}: {error}",
                    extra=extra_context,
                    exc_info=True,
                )


@shared_task
def refresh_dataset(dataset_id: int, healthcheck: bool = False):
    """Refresh the values for all timeseries associated with a specific dataset

    Params:
        dataset_id (int): Primary key of ErddapDataset to refresh all timeseries for
        healthcheck (bool): Should Healthchecks.io be signaled when the dataset has completed updating?
    """
    dataset = ErddapDataset.objects.get(pk=dataset_id)
    dataset.refresh_attempted = timezone.now()
    dataset.save()

    request_refresh_time_seconds = dataset.server.request_refresh_time_seconds

    if healthcheck:
        dataset.healthcheck_start()

    groups = dataset.group_timeseries_by_constraint_and_type()

    for (constraints, _), timeseries in groups.items():
        time.sleep(request_refresh_time_seconds)

        try:
            update_values_for_timeseries(timeseries)
        except BackoffError:
            new_request_refresh_time_seconds = max(request_refresh_time_seconds, 1) * 2
            logger.error(
                f"Some form of timeout encountered while refreshing dataset {dataset_id}"
                f"Increasing backoff from {request_refresh_time_seconds} to "
                "{new_request_refresh_time_seconds}",
                extra={"timeseries": timeseries, "constraints": constraints},
                exc_info=True,
            )
            request_refresh_time_seconds = new_request_refresh_time_seconds

    if healthcheck:
        dataset.healthcheck_complete()


@shared_task
def single_refresh_dataset(dataset_id: int, healthcheck: bool = False):
    """Schedule dataset refresh, only if it does not already exist"""
    with push_scope() as scope:
        scope.set_tag("dataset_id", dataset_id)

        already_queued = task_queued(
            "deployments.tasks.refresh_dataset",
            [dataset_id],
            {"healthcheck": healthcheck},
        )

        if already_queued:
            logger.error(
                f"refresh_dataset is already queued for {dataset_id}. Not going to schedule another.",
                exc_info=True,
            )
        else:
            refresh_dataset.delay(dataset_id, healthcheck=healthcheck)


@shared_task
def refresh_server(server_id: int, healthcheck: bool = False):
    """Refresh all the timeseries data for a server

    Params:
        server_id (int): Primary key of ErddapServer to update all TimeSeries for
        healthcheck (int): Should Healthchecks.io be singled after all timeseries are updated
    """
    server = ErddapServer.objects.get(pk=server_id)

    if healthcheck:
        server.healthcheck_start()

    for ds in server.erddapdataset_set.all():
        refresh_dataset(ds.id)

    if healthcheck:
        server.healthcheck_complete()


@shared_task
def single_refresh_server(server_id: int, healthcheck: bool = False):
    """Schedule dataset refresh, only if it does not already exist"""
    with push_scope() as scope:
        scope.set_tag("server_id", server_id)

        already_queued = task_queued(
            "deployments.tasks.refresh_dataset",
            [server_id],
            {"healthcheck": healthcheck},
        )

        if already_queued:
            logger.error(
                f"refresh_server is already queued for {server_id}. Not going to schedule another.",
                exc_info=True,
            )
        else:
            refresh_server.delay(server_id, healthcheck=healthcheck)
