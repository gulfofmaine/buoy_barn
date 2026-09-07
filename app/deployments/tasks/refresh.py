import logging
import time

import pandas as pd
import sentry_sdk
from celery import shared_task
from django.utils import timezone
from httpcore import ConnectError
from httpx import HTTPError, TimeoutException

from buoy_barn.observability import metrics
from deployments.models import ErddapDataset, ErddapServer, SystemMessage, TimeSeries
from deployments.utils.erddap_datasets import (
    TIME_COLUMN,
    VALUE_COLUMN,
    filter_dataframe,
    retrieve_dataframe,
)
from deployments.utils.system_messages import record_system_message, resolve_system_messages

from .error_handling import BackoffError, Outcome, handle_http_errors
from .extrema import extrema_for_timeseries
from .queue import task_queued

logger = logging.getLogger(__name__)

#: Swallowed `handle_http_errors` outcomes worth a SystemMessage, mapped to the (code, level)
#: to record it at. A dict rather than a chain of ifs, so adding a new outcome forces a
#: decision about its message instead of silently emitting nothing.
#:
#: `time_range_retired` is deliberately absent: `handle_500_time_range_error` already records
#: `end_time_retired` for it, one message per affected timeseries rather than one per dataset,
#: which is the more precise subject -- it names the exact platform that stopped refreshing
#: instead of a dataset-wide "something is wrong".
#:
#: The benign outcomes (`success`, `no_rows`, and the fetch-succeeded-but-empty case) are
#: absent for the same reason `BENIGN_OUTCOMES` exists in `error_handling.py`: the level a
#: handler logs at says whether its condition is benign, and recording a SystemMessage for one
#: would turn a routine empty response into standing dashboard noise.
_FETCH_FAILURE_MESSAGES: dict[str, tuple[str, str]] = {
    Outcome.FORBIDDEN: (SystemMessage.Code.FORBIDDEN, SystemMessage.Level.DANGER),
    Outcome.NOT_FOUND: (SystemMessage.Code.NOT_FOUND, SystemMessage.Level.DANGER),
    Outcome.UNRECOGNIZED_VARIABLE: (
        SystemMessage.Code.UNRECOGNIZED_VARIABLE,
        SystemMessage.Level.WARNING,
    ),
    Outcome.UNRECOGNIZED_CONSTRAINT: (
        SystemMessage.Code.UNRECOGNIZED_CONSTRAINT,
        SystemMessage.Level.WARNING,
    ),
    Outcome.SERVER_ERROR: (SystemMessage.Code.SERVER_ERROR, SystemMessage.Level.WARNING),
    Outcome.UNKNOWN_ERROR: (SystemMessage.Code.UNKNOWN_ERROR, SystemMessage.Level.WARNING),
}

#: Derived from `_FETCH_FAILURE_MESSAGES` rather than listed again, so the "what gets recorded
#: on failure" set and the "what gets resolved on success" set cannot drift apart.
_FETCH_FAILURE_CODES = tuple(code for code, _level in _FETCH_FAILURE_MESSAGES.values())


def update_values_for_timeseries(timeseries: list[TimeSeries], clear_end_time: bool = False):  # noqa: PLR0912 PLR0915
    """Update values and most recent times for a group of timeseries that have the same constraints

    Args:
        timeseries: List of timeseries to update
        clear_end_time: If True, clear the end_time field when data is successfully retrieved
    """
    # A dataset is fetched once per (constraints, timeseries_type) group, so the group id is
    # what distinguishes one failing group from its healthy siblings in the metrics. It is
    # opaque on purpose, the exporter publishes buoybarn.erddap.constraint_group.info to map
    # it back, and it is logged below for when you are already reading logs.
    constraint_group = metrics.constraint_group_id(timeseries[0].constraints)

    with (
        sentry_sdk.new_scope() as scope,
        metrics.erddap_request(
            timeseries[0].dataset.server,
            timeseries[0].dataset.name,
            constraint_group=constraint_group,
            timeseries_type=timeseries[0].timeseries_type,
        ) as outcome,
    ):
        scope.set_tag("erddap-server", timeseries[0].dataset.server)
        scope.set_tag("erddap-dataset", timeseries[0].dataset.name)
        scope.set_tag("erddap-constraint-group", constraint_group)

        logger.info(f"Working on timeseries: {timeseries} (group {constraint_group})")
        try:
            timeseries_df = retrieve_dataframe(
                timeseries[0].dataset.server,
                timeseries[0].dataset.name,
                timeseries[0].constraints,
                timeseries,
            )

        except (ConnectError, TimeoutException) as error:
            outcome.set(Outcome.TIMEOUT)
            raise BackoffError(
                f"Timeout when trying to retrieve dataset {timeseries[0].dataset.name} "
                f"with constraint {timeseries[0].constraints}: {error}",
            ) from error

        except HTTPError as error:
            # The handlers return the specific outcome they recognised ("not_found",
            # "no_rows", ...) or "" when they did not, and may raise BackoffError -- which
            # the context manager classifies on its way out.
            handled = handle_http_errors(timeseries, error)

            fetch_failure = _FETCH_FAILURE_MESSAGES.get(handled)
            if fetch_failure is not None:
                code, level = fetch_failure
                record_system_message(
                    timeseries[0].dataset,
                    code,
                    (
                        f"Fetching {timeseries[0].dataset.name} with constraints "
                        f"{timeseries[0].constraints} failed ({handled}): {error}"
                    ),
                    level=level,
                    constraint_group=constraint_group,
                    context={
                        # `dataset` and `server` are what `observability.promql.query_for`
                        # needs to build this message's own history query, so they are
                        # recorded even though the subject already implies them -- the query
                        # is built at render time from `context` alone, without a database
                        # round trip back to the subject.
                        "dataset": timeseries[0].dataset.name,
                        "server": str(timeseries[0].dataset.server),
                        "constraints": timeseries[0].constraints,
                        "error": str(error),
                    },
                )

            outcome.set(handled or Outcome.UNKNOWN_ERROR)
            if handled:
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
            outcome.set(Outcome.OS_ERROR)
            return

        # Row count separates "the server answered with data" from "the server answered
        # with nothing", which previously only showed up as a warning with its context
        # commented out. Per-series save failures below are deliberately *not* folded into
        # this outcome: the fetch itself succeeded, and those show up in buoybarn.log.records.
        rows = len(timeseries_df)
        outcome.set(Outcome.SUCCESS if rows else Outcome.EMPTY_DATAFRAME, rows=rows)

        # The fetch itself succeeded -- whether or not it returned rows -- so whatever fetch
        # failure was previously recorded against this dataset and constraint group is over.
        # Without this the list of outstanding messages only ever grows.
        resolve_system_messages(
            timeseries[0].dataset,
            *_FETCH_FAILURE_CODES,
            constraint_group=constraint_group,
        )

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

                new_value_time = pd.to_datetime(time)

                # Clear end_time if requested AND we have fresh data
                # Only clear if the new data is more recent than the end_time
                # This prevents clearing end_time on dataset reloads without new data
                if clear_end_time and series.end_time is not None and (new_value_time > series.end_time):
                    previous_end_time = series.end_time
                    logger.info(
                        f"Clearing end_time for {series} - new data at {new_value_time} is after "
                        f"end_time {series.end_time}",
                    )
                    series.end_time = None

                    record_system_message(
                        series,
                        SystemMessage.Code.END_TIME_CLEARED,
                        (
                            f"New data arrived at {new_value_time.isoformat()}, after the "
                            f"previously recorded end_time of {previous_end_time.isoformat()}, "
                            "so Buoy Barn cleared end_time. This timeseries will refresh and "
                            "display again."
                        ),
                        level=SystemMessage.Level.INFO,
                        context={
                            "dataset": series.dataset.name,
                            "server": str(series.dataset.server),
                            "new_value_time": new_value_time.isoformat(),
                            "previous_end_time": previous_end_time.isoformat(),
                        },
                    )
                    # This un-retirement resolves the retirement message that caused it,
                    # whatever constraint group recorded it -- clearing end_time has no single
                    # constraint group of its own to scope the resolution by.
                    resolve_system_messages(series, SystemMessage.Code.END_TIME_RETIRED)

                series.value_time = new_value_time
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
def refresh_dataset(dataset_id: int, healthcheck: bool = False, clear_end_time: bool = False):
    """Refresh the values for all timeseries associated with a specific dataset

    Params:
        dataset_id (int): Primary key of ErddapDataset to refresh all timeseries for
        healthcheck (bool): Should Healthchecks.io be signaled when the dataset has completed updating?
        clear_end_time (bool): If True, clear the end_time field for timeseries
            when data is successfully retrieved
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
            update_values_for_timeseries(timeseries, clear_end_time=clear_end_time)
        except BackoffError:
            new_request_refresh_time_seconds = max(request_refresh_time_seconds, 1) * 2
            logger.error(
                f"Some form of timeout encountered while refreshing dataset {dataset_id}"
                f"Increasing backoff from {request_refresh_time_seconds} to "
                f"{new_request_refresh_time_seconds}",
                extra={"timeseries": timeseries, "constraints": constraints},
                exc_info=True,
            )
            # This increase is per-run only (issue #1838): it lives on a local variable and
            # is discarded when this task ends, so the message says so up front -- otherwise
            # whoever reads it goes looking for a persisted backoff value in the admin that
            # does not exist.
            record_system_message(
                dataset,
                SystemMessage.Code.BACKOFF_INCREASED,
                (
                    f"Backing off after a timeout: the per-request delay increased from "
                    f"{request_refresh_time_seconds}s to {new_request_refresh_time_seconds}s. "
                    "This increase is per-run only -- it is discarded when this task ends, so "
                    "there is nothing persisted to look for here in the admin."
                ),
                level=SystemMessage.Level.WARNING,
                context={
                    # `server` rather than `dataset`: backoff is a property of the server
                    # being slow, so the query this message links to is the request-duration
                    # histogram for the server, not the dataset's outcome counter.
                    "server": str(dataset.server),
                    "dataset": dataset.name,
                    "previous_request_refresh_time_seconds": request_refresh_time_seconds,
                    "new_request_refresh_time_seconds": new_request_refresh_time_seconds,
                    "constraints": constraints,
                },
            )
            request_refresh_time_seconds = new_request_refresh_time_seconds

    if healthcheck:
        dataset.healthcheck_complete()


@shared_task
def single_refresh_dataset(dataset_id: int, healthcheck: bool = False, clear_end_time: bool = False):
    """Schedule dataset refresh, only if it does not already exist

    Args:
        dataset_id: Primary key of ErddapDataset to refresh
        healthcheck: Should Healthchecks.io be signaled when complete
        clear_end_time: If True, clear the end_time field for timeseries
            when data is successfully retrieved
    """
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("dataset_id", dataset_id)

        already_queued = task_queued(
            refresh_dataset.name,
            [dataset_id],
            {"healthcheck": healthcheck, "clear_end_time": clear_end_time},
        )

        if already_queued:
            logger.error(
                f"refresh_dataset is already queued for {dataset_id}. Not going to schedule another.",
                exc_info=True,
            )
        else:
            refresh_dataset.delay(dataset_id, healthcheck=healthcheck, clear_end_time=clear_end_time)


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
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("server_id", server_id)

        already_queued = task_queued(
            refresh_server.name,
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
