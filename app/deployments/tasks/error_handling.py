import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone
from requests import HTTPError

try:
    from pandas.core.indexes.period import DateParseError, parse_time_string
except ImportError:
    from pandas._libs.tslibs.parsing import DateParseError, parse_time_string

logger = logging.getLogger(__name__)


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
