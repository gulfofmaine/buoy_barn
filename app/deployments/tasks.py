import logging
import time
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from pandas import Timedelta
from requests import HTTPError, Timeout
from sentry_sdk import push_scope

try:
    from pandas.core.indexes.period import DateParseError, parse_time_string
except ImportError:
    from pandas._libs.tslibs.parsing import parse_time_string, DateParseError

from deployments.models import ErddapDataset, ErddapServer
from deployments.utils.erddap_datasets import filter_dataframe, retrieve_dataframe

logger = logging.getLogger(__name__)


def update_values_for_timeseries(timeseries):
    """Update values and most recent times for a group of timeseries that have the same constraints"""
    with push_scope() as scope:
        scope.set_tag("erddap-server", timeseries[0].dataset.server)
        scope.set_tag("erddap-dataset", timeseries[0].dataset.name)

        logger.info(f"Working on timeseries: {timeseries}")
        try:
            df = retrieve_dataframe(
                timeseries[0].dataset.server,
                timeseries[0].dataset.name,
                timeseries[0].constraints,
                timeseries,
            )

        except HTTPError as error:
            if handle_http_errors(timeseries, error):
                return

        except Timeout as error:
            raise BackoffError(
                f"Timeout when trying to retrieve dataset {timeseries[0].dataset.name} "
                f"with constraint {timeseries[0].constraints}: {error}",
            )

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
            filtered_df = filter_dataframe(df, series.variable)

            try:
                row = filtered_df.iloc[-1]
            except IndexError:
                logger.error(
                    f"Unable to find position in dataframe for {series.platform.name} - "
                    f"{series.variable}",
                    extra={
                        "timeseries": timeseries,
                        "constraints": timeseries[0].constraints,
                    },
                    exc_info=True,
                )
                return

            try:
                variable_name = [
                    key for key in row.keys() if key.split(" ")[0] == series.variable
                ]
                value = row[variable_name]

                if isinstance(value, Timedelta):
                    logger.info("Converting from Timedelta to seconds")
                    value = value.seconds

                series.value = value
                time = row["time (UTC)"]
                series.value_time = parse_time_string(time)[0]
                series.save()
            except TypeError as error:
                logger.error(
                    f"Could not save {series.variable} from {row}: {error}",
                    extra={
                        "timeseries": timeseries,
                        "constraints": timeseries[0].constraints,
                    },
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

    groups = dataset.group_timeseries_by_constraint()

    for constraints, timeseries in groups.items():
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


def task_queued(task_name: str, task_args: list, task_kwargs: dict) -> bool:
    """Returns true if the task is already scheduled"""
    from buoy_barn.celery import app
    from celery.app.control import Control

    control = Control(app)
    inspect = control.inspect()

    for worker_tasks in inspect.active().values():
        for task in worker_tasks:
            if task["name"] == task_name and task["args"] == task_args:
                return True

    for worker_tasks in inspect.reserved().values():
        for task in worker_tasks:
            if task["name"] == task_name and task["args"] == task_args:
                return True

    for worker_tasks in inspect.scheduled().values():
        for task in worker_tasks:
            if task["name"] == task_name and task["args"] == task_args:
                return True

    return False


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
                f"refresh_dataset is already queued for {dataset_id}. "
                "Not going to schedule another.",
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
                f"refresh_server is already queued for {server_id}. "
                "Not going to schedule another.",
                exc_info=True,
            )
        else:
            refresh_server.delay(server_id, healthcheck=healthcheck)


def handle_500_no_rows_error(timeseries_group, compare_text: str) -> bool:
    """Did the request not return any rows? Returns true if handled"""
    if "nRows = 0" in compare_text:
        logger.info(
            f"{timeseries_group[0].dataset.name} with constraints "
            f"{timeseries_group[0].constraints} did not return any results",
        )
        return True

    return False


def handle_500_variable_actual_range_error(timeseries_group, compare_text: str) -> bool:
    """Did the request ask for a value that was outside of the real range of a value?

    Returns True if handled.
    """
    if (
        "Your query produced no matching results" in compare_text
        and "is outside of the variable&#39;s actual_range" in compare_text
    ):
        logger.error(
            (
                f"{timeseries_group[0].dataset.name} "
                f"with constraints {timeseries_group[0].constraints} had a "
                "constraint outside of normal range"
            ),
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return True

    return False


def handle_500_time_range_error(timeseries_group, compare_text: str) -> bool:
    """Did the request fall outside the range of times for the dataset

    returns True if handled"""
    if "is outside of the variable" in compare_text:
        try:
            times_str = compare_text.rpartition("actual_range:")[-1].rpartition(")")[0]
        except (AttributeError, IndexError) as e:
            logger.error(
                (
                    f"Unable to access and attribute or index of {timeseries_group[0].dataset.name} "
                    f"with constraint {timeseries_group[0].constraints}: {e}"
                ),
                extra=error_extra(timeseries_group, compare_text),
                exc_info=True,
            )
            return False

        times = []
        for potential_time in times_str.split(" "):
            try:
                time = parse_time_string(potential_time)
                times.append(time[0])
            except (DateParseError, ValueError):
                pass
        times.sort(reverse=True)

        try:
            end_time = times[0]
        except IndexError:
            logger.error(
                (
                    "Unable to parse datetimes in error processing dataset "
                    f"{timeseries_group[0].dataset.name} with constraint "
                    f"{timeseries_group[0].constraints}"
                ),
                extra=error_extra(timeseries_group, compare_text),
                exc_info=True,
            )
            return False

        week_ago = timezone.now() - timedelta(days=7)

        if end_time < week_ago:
            for ts in timeseries_group:
                ts.end_time = end_time
                ts.save()

                logger.error(
                    f"Set end time for {ts} to {end_time} based on responses",
                    extra=error_extra(timeseries_group, compare_text),
                    exc_info=True,
                )

        return True

    return False


def error_extra(timeseries_group, compare_text: str = None):
    """Return dictionary of extra values for timeseries group errors"""
    extra = {
        "timeseries": timeseries_group,
        "constraints": timeseries_group[0].constraints,
        "server": timeseries_group[0].dataset.server,
        "dataset_id": timeseries_group[0].dataset.name,
    }

    if compare_text:
        extra["response_text"] = compare_text

    return extra


class BackoffError(Exception):
    """Raise when a timeout occurs to trigger a backoff and slow down requests"""


def handle_500_unrecognized_constraint(timeseries_group, compare_text: str) -> bool:
    """Handle when one of the constraints is invalid

    returns True if handled
    """
    if "Unrecognized constraint variable=" in compare_text:
        logger.error(
            (
                f"Invalid constraint variable for dataset {timeseries_group[0].dataset.name} "
                f"with constraints {timeseries_group[0].constraints}"
            ),
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return True

    return False


def handle_500_errors(timeseries_group, compare_text: str) -> bool:
    """Handle various types of known 500 errors"""
    if handle_500_no_rows_error(timeseries_group, compare_text):
        return True

    if handle_500_time_range_error(timeseries_group, compare_text):
        return True

    if handle_500_variable_actual_range_error(timeseries_group, compare_text):
        return True

    if handle_500_unrecognized_constraint(timeseries_group, compare_text):
        return True

    return False


def handle_400_errors(timeseries_group, compare_text: str, error: Exception) -> bool:
    """Handle various types of known 400 errors"""
    if handle_400_unrecognized_variable(timeseries_group, compare_text):
        return True

    if handle_404_errors(timeseries_group, compare_text):
        return True

    if handle_429_too_many_requests(timeseries_group, compare_text, error):
        return True

    if handle_408_request_timeout(timeseries_group, compare_text, error):
        return True

    return False


def handle_408_request_timeout(
    timeseries_group,
    compare_text: str,
    error: Exception,
) -> bool:
    """Handle 408 timeouts"""
    if "code=408" in compare_text and "TimeoutException" in compare_text:
        raise BackoffError(
            f"Too many requests to server {timeseries_group[0].dataset.server}",
        ) from error

    return False


def handle_429_too_many_requests(
    timeseries_group,
    compare_text: str,
    error: Exception,
) -> bool:
    """Too many requests too quickly to the server"""
    if "Too Many Requests" in compare_text and "code=429" in compare_text:
        raise BackoffError(
            f"Too many requests to server {timeseries_group[0].dataset.server}",
        ) from error

    return False


def handle_400_unrecognized_variable(timeseries_group, compare_text: str) -> bool:
    """When there is an unrecognized variable requested"""
    if "Unrecognized variable=" in compare_text:
        logger.error(
            f"Unrecognized variable for dataset {timeseries_group[0].dataset.name}",
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return True
    return False


def handle_404_errors(timeseries_group, compare_text: str) -> bool:
    """Handle known types of 404 errors"""
    if handle_404_no_matching_dataset_id(timeseries_group, compare_text):
        return True

    if handle_404_no_matching_station(timeseries_group, compare_text):
        return True

    if handle_404_no_matching_time(timeseries_group, compare_text):
        return True

    if handle_404_dataset_file_not_found(timeseries_group, compare_text):
        return True

    return False


def handle_404_dataset_file_not_found(timeseries_group, compare_text: str) -> bool:
    if "java.io.FileNotFoundException" in compare_text and "code=404" in compare_text:
        logger.error(
            f"{timeseries_group[0].dataset.name} does not exist on the server",
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return True

    return False


def handle_404_no_matching_time(timeseries_group, compare_text: str) -> bool:
    """Handle when the station does not have time for the current request"""
    if "No data matches time" in compare_text and "code=404" in compare_text:
        logger.error(
            f"{timeseries_group[0].dataset.name} does not currently have a valid time",
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return True

    return False


def handle_404_no_matching_station(timeseries_group, compare_text: str) -> bool:
    """Handle when the station constraint does not exist in dataset"""
    if (
        "Your query produced no matching results" in compare_text
        and "There are no matching stations" in compare_text
    ):
        logger.error(
            (
                f"{timeseries_group[0].dataset.name} does not have a requested station. "
                "Please check the constraints"
            ),
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return True

    return False


def handle_404_no_matching_dataset_id(timeseries_group, compare_text: str) -> bool:
    """Handle when the Dataset does not exist on the ERDDAP server"""
    if (
        "Resource not found" in compare_text
        and "Currently unknown datasetID" in compare_text
    ):
        logger.error(
            (
                f"{timeseries_group[0].dataset.name} is currently unknown by the server. "
                "Please investigate if the dataset has moved"
            ),
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return True

    return False


def handle_http_errors(timeseries_group, error: HTTPError) -> bool:
    """Handle various types of HTTPErrors. Returns True if handled"""

    try:
        if error.response.status_code == 403:
            logger.error(
                (
                    f"403 error loading dataset {timeseries_group[0].dataset.name}. "
                    "NOAA Coastwatch most likely blacklisted us. "
                    "Try running the request manually from the worker pod to "
                    f"replicate the error and access the returned text. {error}"
                ),
                extra=error_extra(timeseries_group),
                exc_info=True,
            )
            return True

        if error.response.status_code == 404:
            logger.error(
                (
                    f"No rows found for {timeseries_group[0].dataset.name} "
                    f"with constraint {timeseries_group[0].constraints}: {error}"
                ),
                extra=error_extra(timeseries_group),
                exc_info=True,
            )
            return True

        if error.response.status_code == 408:
            raise BackoffError("408 Backoff encountered") from error

        if error.response.status_code == 500:
            url = error.request.url

            response_500 = requests.get(url, timeout=settings.ERDDAP_TIMEOUT_SECONDS)

            if handle_500_errors(timeseries_group, response_500.text):
                return True

            logger.error(
                (
                    f"500 error loading dataset {timeseries_group[0].dataset.name} "
                    f"with constraint {timeseries_group[0].constraints}: {error} "
                ),
                extra=error_extra(timeseries_group, response_500.text),
                exc_info=True,
            )
            return True

        logger.error(
            (
                f"{error.response.status_code} error loading dataset {timeseries_group[0].dataset.name}"
                f" with constraint {timeseries_group[0].constraints}: {error}"
            ),
            extra=error_extra(timeseries_group),
            exc_info=True,
        )
        return True

    except AttributeError:
        pass

    if handle_400_errors(timeseries_group, str(error), error):
        return True

    if handle_500_errors(timeseries_group, str(error)):
        return True

    logger.error(
        (
            f"Error loading dataset {timeseries_group[0].dataset.name} "
            f"with constraint {timeseries_group[0].constraints}: {error}. "
            "Could not find an existing error defined."
        ),
        extra=error_extra(timeseries_group),
        exc_info=True,
    )
    return True
