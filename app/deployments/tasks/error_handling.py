import logging
from datetime import timedelta
from http import HTTPStatus

import pandas as pd
from django.utils import timezone
from httpx import HTTPError, HTTPStatusError

from buoy_barn.observability import metrics
from deployments.models import SystemMessage
from deployments.utils.system_messages import record_system_message

from .outcomes import NOT_HANDLED, Outcome

logger = logging.getLogger(__name__)


def handle_500_no_rows_error(timeseries_group, compare_text: str) -> str:
    """Did the request not return any rows? Returns true if handled"""
    if "nRows = 0" in compare_text:
        logger.info(
            f"{timeseries_group[0].dataset.name} with constraints "
            f"{timeseries_group[0].constraints} did not return any results",
        )
        return Outcome.NO_ROWS

    return NOT_HANDLED


def handle_500_variable_actual_range_error(timeseries_group, compare_text: str) -> str:
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
        return Outcome.CONSTRAINT_OUT_OF_RANGE

    return NOT_HANDLED


def handle_500_time_range_error(timeseries_group, compare_text: str) -> str:
    """Did the request fall outside the range of times for the dataset

    returns True if handled
    """
    if "is outside of the variable" in compare_text:
        try:
            times_str = compare_text.rpartition("actual_range: ")[-1].rpartition(")")[0]
        except (AttributeError, IndexError) as e:
            logger.error(
                (
                    f"Unable to access and attribute or index of {timeseries_group[0].dataset.name} "
                    f"with constraint {timeseries_group[0].constraints}: {e}"
                ),
                extra=error_extra(timeseries_group, compare_text),
                exc_info=True,
            )
            return NOT_HANDLED

        times = []
        for potential_time in times_str.split(" to "):
            try:
                time = pd.to_datetime(potential_time)
                times.append(time)
            except ValueError:  # noqa: PERF203
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
            return NOT_HANDLED

        week_ago = timezone.now() - timedelta(days=7)

        if end_time < week_ago:
            constraint_group = metrics.constraint_group_id(timeseries_group[0].constraints)

            for ts in timeseries_group:
                ts.end_time = end_time
                ts.save()

                logger.error(
                    f"Set end time for {ts} to {end_time} based on responses",
                    extra=error_extra(timeseries_group, compare_text),
                    exc_info=True,
                )

                # Writing end_time drops this series out of `refreshable()`, so it stops
                # being refreshed and displayed. The message is addressed to the admin who
                # has to decide whether that was correct.
                record_system_message(
                    ts,
                    SystemMessage.Code.END_TIME_RETIRED,
                    (
                        f"ERDDAP reported that {timeseries_group[0].dataset.name}'s data ends "
                        f"at {end_time.isoformat()}, so Buoy Barn set this timeseries' end_time "
                        "to that value. It will no longer be refreshed or displayed on Mariners "
                        "Dashboard. If the platform is actually still live, use the "
                        '"Remove end time for timeseries" action on this Platform in the admin '
                        "to undo this."
                    ),
                    level=SystemMessage.Level.DANGER,
                    constraint_group=constraint_group,
                    context={
                        "end_time": end_time.isoformat(),
                        "dataset": timeseries_group[0].dataset.name,
                        "server": str(timeseries_group[0].dataset.server),
                        "constraints": timeseries_group[0].constraints,
                    },
                )

            return Outcome.TIME_RANGE_RETIRED

        # ERDDAP reported an actual_range ending inside the last week, recent enough that
        # nothing was retired. Distinct from TIME_RANGE_RETIRED so a dataset map lookup
        # doesn't claim a retirement that didn't happen.
        return Outcome.TIME_RANGE_REPORTED

    return NOT_HANDLED


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


def handle_500_unrecognized_constraint(timeseries_group, compare_text: str) -> str:
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
        return Outcome.UNRECOGNIZED_CONSTRAINT

    return NOT_HANDLED


def handle_500_errors(timeseries_group, compare_text: str) -> str:
    """Handle various types of known 500 errors. Returns the outcome, or NOT_HANDLED."""
    for handler in (
        handle_500_no_rows_error,
        handle_500_time_range_error,
        handle_500_variable_actual_range_error,
        handle_400_unrecognized_variable,
        handle_500_unrecognized_constraint,
    ):
        outcome = handler(timeseries_group, compare_text)
        if outcome:
            return outcome

    return NOT_HANDLED


def handle_400_errors(timeseries_group, compare_text: str, error: Exception) -> str:
    """Handle various types of known 400 errors. Returns the outcome, or NOT_HANDLED.

    Not a loop like its siblings because the 429/408 handlers also need `error` to chain
    the BackoffError they raise.
    """
    outcome = handle_400_unrecognized_variable(timeseries_group, compare_text)
    if outcome:
        return outcome

    outcome = handle_404_errors(timeseries_group, compare_text)
    if outcome:
        return outcome

    outcome = handle_429_too_many_requests(timeseries_group, compare_text, error)
    if outcome:
        return outcome

    return handle_408_request_timeout(timeseries_group, compare_text, error)


def handle_408_request_timeout(
    timeseries_group,
    compare_text: str,
    error: Exception,
) -> str:
    """Handle 408 timeouts"""
    if "code=408" in compare_text and "TimeoutException" in compare_text:
        raise BackoffError(
            f"Too many requests to server {timeseries_group[0].dataset.server}",
        ) from error

    return NOT_HANDLED


def handle_429_too_many_requests(
    timeseries_group,
    compare_text: str,
    error: Exception,
) -> str:
    """Too many requests too quickly to the server"""
    if "Too Many Requests" in compare_text and "code=429" in compare_text:
        raise BackoffError(
            f"Too many requests to server {timeseries_group[0].dataset.server}",
        ) from error

    return NOT_HANDLED


def handle_400_unrecognized_variable(timeseries_group, compare_text: str) -> str:
    """When there is an unrecognized variable requested"""
    if "Unrecognized variable=" in compare_text:
        logger.error(
            f"Unrecognized variable for dataset {timeseries_group[0].dataset.name}",
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return Outcome.UNRECOGNIZED_VARIABLE
    return NOT_HANDLED


def handle_404_errors(timeseries_group, compare_text: str) -> str:
    """Handle known types of 404 errors. Returns the outcome, or NOT_HANDLED."""
    for handler in (
        handle_404_no_matching_dataset_id,
        handle_404_no_matching_station,
        handle_404_no_matching_time,
        handle_404_dataset_file_not_found,
    ):
        outcome = handler(timeseries_group, compare_text)
        if outcome:
            return outcome

    return NOT_HANDLED


def handle_404_dataset_file_not_found(timeseries_group, compare_text: str) -> str:
    if "java.io.FileNotFoundException" in compare_text and "code=404" in compare_text:
        logger.error(
            f"{timeseries_group[0].dataset.name} does not exist on the server",
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return Outcome.NOT_FOUND

    return NOT_HANDLED


def handle_404_no_matching_time(timeseries_group, compare_text: str) -> str:
    """Handle when the station does not have time for the current request"""
    if "No data matches time" in compare_text and "code=404" in compare_text:
        logger.error(
            f"{timeseries_group[0].dataset.name} does not currently have a valid time",
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return Outcome.NO_MATCHING_TIME

    return NOT_HANDLED


def handle_404_no_matching_station(timeseries_group, compare_text: str) -> str:
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
        return Outcome.NOT_FOUND

    return NOT_HANDLED


def handle_404_no_matching_dataset_id(timeseries_group, compare_text: str) -> str:
    """Handle when the Dataset does not exist on the ERDDAP server"""
    if "Resource not found" in compare_text and "Currently unknown datasetID" in compare_text:
        logger.error(
            (
                f"{timeseries_group[0].dataset.name} is currently unknown by the server. "
                "Please investigate if the dataset has moved"
            ),
            extra=error_extra(timeseries_group, compare_text),
            exc_info=True,
        )
        return Outcome.NOT_FOUND

    return NOT_HANDLED


def handle_http_errors(timeseries_group, error: HTTPError) -> str:  # noqa: PLR0911
    """Handle various types of HTTPErrors.

    Returns the outcome that was recognised, or NOT_HANDLED (falsy) if it was not. Every
    branch below is currently "handled", which is exactly why the outcome string matters:
    the caller cannot distinguish a benign empty response from a blacklisted server by
    return value alone.
    """
    if isinstance(error.__cause__, HTTPStatusError):
        try:
            if error.__cause__.response.status_code == HTTPStatus.FORBIDDEN:
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
                return Outcome.FORBIDDEN

            if error.__cause__.response.status_code == HTTPStatus.NOT_FOUND:
                outcome = handle_404_errors(timeseries_group, error.__cause__.response.text)
                if outcome:
                    return outcome

            if error.__cause__.response.status_code == HTTPStatus.REQUEST_TIMEOUT:
                raise BackoffError("408 Backoff encountered") from error

            if error.__cause__.response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR:
                outcome = handle_500_errors(timeseries_group, error.__cause__.response.text)
                if outcome:
                    return outcome

                logger.error(
                    (
                        f"500 error loading dataset {timeseries_group[0].dataset.name} "
                        f"with constraint {timeseries_group[0].constraints}: {error} "
                    ),
                    extra=error_extra(timeseries_group, error.__cause__.response.text),
                    exc_info=True,
                )
                return Outcome.SERVER_ERROR

            logger.error(
                (
                    f"{error.response.status_code} error loading dataset "
                    + timeseries_group[0].dataset.name
                    + f" with constraint {timeseries_group[0].constraints}: {error}"
                ),
                extra=error_extra(timeseries_group),
                exc_info=True,
            )
            return Outcome.UNKNOWN_ERROR

        except AttributeError:
            pass

    outcome = handle_400_errors(timeseries_group, str(error), error)
    if outcome:
        return outcome

    outcome = handle_500_errors(timeseries_group, str(error))
    if outcome:
        return outcome

    logger.error(
        (
            f"Error loading dataset {timeseries_group[0].dataset.name} "
            f"with constraint {timeseries_group[0].constraints}: {error}. "
            "Could not find an existing error defined."
        ),
        extra=error_extra(timeseries_group),
        exc_info=True,
    )
    return Outcome.UNKNOWN_ERROR
