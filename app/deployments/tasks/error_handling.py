import logging
from datetime import timedelta
from enum import StrEnum
from http import HTTPStatus

import pandas as pd
from django.utils import timezone
from httpx import HTTPError, HTTPStatusError

logger = logging.getLogger(__name__)

#: Returned by a handler that did not recognise the error, so the caller keeps looking.
#: The handlers return an *outcome string* rather than a bool so the specific failure can
#: be recorded as a metric attribute. Empty string is falsy, so the single call site in
#: `refresh.update_values_for_timeseries` -- `if handle_http_errors(...): return` -- keeps
#: working exactly as it did when these returned True/False.
#:
#: Choosing an outcome string is not a judgement call: **the level a handler logs at says
#: whether its condition is benign.** `handle_500_no_rows_error` logs at INFO and is the
#: only benign outcome (`no_rows`); every other handler logs at ERROR, so each needs an
#: outcome of its own rather than being folded into `no_rows` where a dashboard would treat
#: it as harmless. See the outcome table in docs/observability.md.
NOT_HANDLED = ""


class Outcome(StrEnum):
    """Every outcome the refresh path can report.

    Declared here because this is where they are produced: the handlers below return these,
    and `refresh.py` names the few that describe the fetch itself rather than an error body.
    An enum rather than bare strings so a handler cannot report a mistyped outcome -- which
    would be validated away to "other" by
    :func:`buoy_barn.observability.metrics.erddap_outcomes` and quietly leave the real
    failure off every dashboard.

    ``StrEnum`` specifically, not ``(str, Enum)``: members have to *be* their string, since
    they are returned through ``-> str`` signatures, tested for truthiness against
    :data:`NOT_HANDLED`, and handed to the metrics facade as an attribute value. With the
    older idiom ``str(Outcome.NO_ROWS)`` is ``"Outcome.NO_ROWS"``, which is what would end
    up on the time series.
    """

    # Named by refresh.py around the fetch, not by a handler.
    SUCCESS = "success"
    EMPTY_DATAFRAME = "empty_dataframe"
    TIMEOUT = "timeout"
    BACKOFF = "backoff"
    OS_ERROR = "os_error"
    VALUE_ERROR = "value_error"
    UNKNOWN_ERROR = "unknown_error"

    # Returned by the handlers below.
    NO_ROWS = "no_rows"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"
    TIME_RANGE_RETIRED = "time_range_retired"
    CONSTRAINT_OUT_OF_RANGE = "constraint_out_of_range"
    NO_MATCHING_TIME = "no_matching_time"
    UNRECOGNIZED_VARIABLE = "unrecognized_variable"
    UNRECOGNIZED_CONSTRAINT = "unrecognized_constraint"
    SERVER_ERROR = "server_error"


#: The outcome vocabulary as plain strings, which is what
#: `buoy_barn.observability.metrics` validates the metric attribute against.
OUTCOMES = frozenset(outcome.value for outcome in Outcome)

#: The outcomes that need no attention. Everything else in :class:`Outcome` corresponds to a
#: handler that logs at ERROR, which is what makes "is anything broken?" expressible as
#: `outcome not in BENIGN_OUTCOMES` rather than a list that has to be revised whenever a
#: handler is added.
BENIGN_OUTCOMES = frozenset({Outcome.SUCCESS.value, Outcome.NO_ROWS.value})


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
            for ts in timeseries_group:
                ts.end_time = end_time
                ts.save()

                logger.error(
                    f"Set end time for {ts} to {end_time} based on responses",
                    extra=error_extra(timeseries_group, compare_text),
                    exc_info=True,
                )

        return Outcome.TIME_RANGE_RETIRED

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
