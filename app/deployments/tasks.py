from datetime import timedelta
import logging

from celery import shared_task
from django.utils import timezone
import requests
from requests import HTTPError, Timeout
from pandas import Timedelta

try:
    from pandas.core.indexes.period import parse_time_string, DateParseError
except ImportError:
    from pandas._libs.tslibs.parsing import parse_time_string, DateParseError

from deployments.models import ErddapDataset, ErddapServer
from deployments.utils.erddap_datasets import filter_dataframe, retrieve_dataframe


logger = logging.getLogger(__name__)


def update_values_for_timeseries(timeseries):
    """ Update values and most recent times for a group of timeseries that have the same constraints """
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
        logger.warning(
            f"Timeout when trying to retrieve dataset {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}: {error}",
            extra={"timeseries": timeseries, "constraints": timeseries[0].constraints},
            exc_info=True,
        )
        return

    except OSError as error:
        logger.info(
            f"Error loading dataset {timeseries[0].dataset.name} with constraints {timeseries[0].constraints}: {error}",
            extra={"timeseries": timeseries, "constraints": timeseries[0].constraints},
            exc_info=True,
        )
        return

    for series in timeseries:
        filtered_df = filter_dataframe(df, series.variable)

        try:
            row = filtered_df.iloc[-1]
        except IndexError:
            message = f"Unable to find position in dataframe for {series.platform.name} - {series.variable}"
            logger.warning(message)
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
                f"Could not save {series.variable} from {row}: {error}", exc_info=True
            )


@shared_task
def refresh_dataset(dataset_id: int, healthcheck: bool = False):
    """ Refresh the values for all timeseries associated with a specific dataset 
    
    Params:
        dataset_id (int): Primary key of ErddapDataset to refresh all timeseries for
        healthcheck (bool): Should Healthchecks.io be signaled when the dataset has completed updating?
    """
    dataset = ErddapDataset.objects.get(pk=dataset_id)
    dataset.refresh_attempted = timezone.now()
    dataset.save()

    if healthcheck:
        dataset.healthcheck_start()

    groups = dataset.group_timeseries_by_constraint()

    for constraints, timeseries in groups.items():
        update_values_for_timeseries(timeseries)

    if healthcheck:
        dataset.healthcheck_complete()


@shared_task
def refresh_server(server_id: int, healthcheck: bool = False):
    """ Refresh all the timeseries data for a server 
    
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


def handle_500_no_rows_error(timeseries_group, compare_text: str) -> bool:
    """ Did the request not return any rows? Returns true if handled """
    if "nRows = 0" in compare_text:
        logger.info(
            f"{timeseries_group[0].dataset.name} with constraints {timeseries_group[0].constraints} did not return any results"
        )
        return True

    return False


def handle_500_variable_actual_range_error(timeseries_group, compare_text: str) -> bool:
    """ Did the request ask for a value that was outside of the real range of a value?

    Returns True if handled.
    """
    if (
        "Your query produced no matching results" in compare_text
        and "is outside of the variable&#39;s actual_range" in compare_text
    ):
        logger.info(
            f"{timeseries_group[0].dataset.name} with constraints {timeseries_group[0].constraints} had a constraint outside of normal range"
        )
        return True

    return False


def handle_500_time_range_error(timeseries_group, compare_text: str) -> bool:
    """ Did the request fall outside the range of times for the dataset
    
    returns True if handled """
    if "is outside of the variable" in compare_text:
        try:
            times_str = compare_text.rpartition("actual_range:")[-1].rpartition(")")[0]
        except (AttributeError, IndexError) as e:
            logger.warning(
                f"Unable to access and attribute or index of {timeseries_group[0].dataset.name} with constraint {timeseries_group[0].constraints}: {e}",
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
            logger.warning(
                f"Unable to parse datetimes in error processing dataset {timeseries_group[0].dataset.name} with constraint {timeseries_group[0].constraints}",
                extra=error_extra(timeseries_group, compare_text),
                exc_info=True,
            )
            return False

        week_ago = timezone.now() - timedelta(days=7)

        if end_time < week_ago:
            for ts in timeseries_group:
                ts.end_time = end_time
                ts.save()

                logger.warning(
                    f"Set end time for {ts} to {end_time} based on responses",
                    extra=error_extra(timeseries_group, compare_text),
                    exc_info=True,
                )

        return True

    return False


def error_extra(timeseries_group, compare_text: str = None):
    """ Return dictionary of extra values for timeseries group errors """
    extra = {
        "timeseries": timeseries_group,
        "constraints": timeseries_group[0].constraints,
        "server": timeseries_group[0].dataset.server,
        "dataset_id": timeseries_group[0].dataset.name,
    }

    if compare_text:
        extra["response_text"] = compare_text

    return extra


def handle_500_unrecognized_constraint(timeseries_group, compare_text: str) -> bool:
    """ Handle when one of the constraints is invalid

    returns True if handled
    """
    if "Unrecognized constraint variable=" in compare_text:
        logger.warning(
            f"Invalid constraint variable for dataset {timeseries_group[0].dataset.name} with constraints {timeseries_group[0].constraints}",
            extra=error_extra(timeseries_group, compare_text),
        )
        return True

    return False


def handle_500_errors(timeseries_group, compare_text: str) -> bool:
    """ Handle various types of known 500 errors """
    if handle_500_no_rows_error(timeseries_group, compare_text):
        return True

    if handle_500_time_range_error(timeseries_group, compare_text):
        return True

    if handle_500_variable_actual_range_error(timeseries_group, compare_text):
        return True

    if handle_500_unrecognized_constraint(timeseries_group, compare_text):
        return True

    return False


def handle_400_errors(timeseries_group, compare_text: str) -> bool:
    """ Handle various types of known 400 errors """
    if handle_400_unrecognized_variable(timeseries_group, compare_text):
        return True

    if handle_404_errors(timeseries_group, compare_text):
        return True

    return False


def handle_400_unrecognized_variable(timeseries_group, compare_text: str) -> bool:
    """ When there is an unrecognized variable requested """
    if "Unrecognized variable=" in compare_text:
        logger.warning(
            f"Unrecognized variable for dataset {timeseries_group[0].dataset.name}",
            extra=error_extra(timeseries_group, compare_text),
        )
        return True
    return False


def handle_404_errors(timeseries_group, compare_text: str) -> bool:
    """ Handle known types of 404 errors """
    if handle_404_no_matching_dataset_id(timeseries_group, compare_text):
        return True

    if handle_404_no_matching_station(timeseries_group, compare_text):
        return True

    return False


def handle_404_no_matching_station(timeseries_group, compare_text: str) -> bool:
    """ Handle when the station constraint does not exist in dataset """
    if (
        "Your query produced no matching results" in compare_text
        and "There are no matching stations" in compare_text
    ):
        logger.warning(
            f"{timeseries_group[0].dataset.name} does not have a requested station. Please check the constraints",
            extra=error_extra(timeseries_group, compare_text),
        )
        return True

    return False


def handle_404_no_matching_dataset_id(timeseries_group, compare_text: str) -> bool:
    """ Handle when the Dataset does not exist on the ERDDAP server """
    if (
        "Resource not found" in compare_text
        and "Currently unknown datasetID" in compare_text
    ):
        logger.warning(
            f"{timeseries_group[0].dataset.name} is currently unknown by the server. Please investigate if the dataset has moved",
            extra=error_extra(timeseries_group, compare_text),
        )
        return True

    return False


def handle_http_errors(timeseries_group, error: HTTPError) -> bool:
    """ Handle various types of HTTPErrors. Returns True if handled """

    try:
        if error.response.status_code == 403:
            logger.error(
                f"403 error loading dataset {timeseries_group[0].dataset.name}. "
                + "NOAA Coastwatch most likely blacklisted us. "
                + "Try running the request manually from the worker pod to replicate the error and access the returned text."
                + error,
                extra=error_extra(timeseries_group),
                exc_info=True,
            )
            return True

        if error.response.status_code == 404:
            logger.warning(
                f"No rows found for {timeseries_group[0].dataset.name} with constraint {timeseries_group[0].constraints}: {error}",
                extra=error_extra(timeseries_group),
                exc_info=True,
            )
            return True

        if error.response.status_code == 500:
            url = error.request.url

            response_500 = requests.get(url)

            if handle_500_errors(timeseries_group, response_500.text):
                return True

            logger.info(
                f"500 error loading dataset {timeseries_group[0].dataset.name} with constraint {timeseries_group[0].constraints}: {error} ",
                extra=error_extra(timeseries_group, response_500.text),
                exc_info=True,
            )
            return True

        logger.error(
            f"{error.response.status_code} error loading dataset {timeseries_group[0].dataset.name} with constraint {timeseries_group[0].constraints}: {error}",
            extra=error_extra(timeseries_group),
            exc_info=True,
        )
        return True

    except AttributeError:
        pass

    if handle_400_errors(timeseries_group, str(error)):
        return True

    if handle_500_errors(timeseries_group, str(error)):
        return True

    logger.error(
        f"Error loading dataset {timeseries_group[0].dataset.name} with constraint {timeseries_group[0].constraints}: {error}",
        extra=error_extra(timeseries_group),
        exc_info=True,
    )
    return True
