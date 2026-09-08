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

from .error_handling import BackoffError, handle_http_errors
from .extrema import extrema_for_timeseries
from .outcomes import FETCH_FAILURE_CODES, FETCH_FAILURE_MESSAGES, RESOLVED_ON_SUCCESS, Outcome
from .queue import task_queued

logger = logging.getLogger(__name__)

# `time_range_reported` didn't fail (the generic "failed" sentence below would be wrong for it),
# so it gets its own text instead of an entry in `FETCH_FAILURE_MESSAGES`'s message shape.
_TIME_RANGE_REPORTED_MESSAGE = (
    "ERDDAP reported that this dataset's data ends soon, but recently enough that Buoy Barn "
    "left every timeseries in this constraint group alone: {error}"
)


def _fetch_failure_message(dataset, constraints, handled, error) -> str:
    if handled == Outcome.TIME_RANGE_REPORTED:
        return _TIME_RANGE_REPORTED_MESSAGE.format(error=error)
    return f"Fetching {dataset.name} with constraints {constraints} failed ({handled}): {error}"


def _resolve_stale_fetch_failures(dataset, constraint_group, codes, keep=None):
    """Resolve `codes` for `dataset`+`constraint_group`, except `keep`.

    Called on all outcomes, so a dataset that switches failure
    mode (403 -> 404) does not leave the old message outstanding forever.
    """
    codes = tuple(code for code in codes if code != keep)
    if codes:
        resolve_system_messages(dataset, *codes, constraint_group=constraint_group)


def update_values_for_timeseries(timeseries: list[TimeSeries], clear_end_time: bool = False):  # noqa: PLR0912 PLR0915
    """Update values and most recent times for a group of timeseries that have the same constraints

    Args:
        timeseries: List of timeseries to update
        clear_end_time: If True, clear the end_time field when data is successfully retrieved
    """
    # The group id distinguishes one failing constraint group from its healthy siblings.
    # Opaque on purpose -- buoybarn.erddap.constraint_group.info maps it back to real
    # constraints, and it's logged below for when you're already reading logs, not a dashboard.
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

            fetch_failure = FETCH_FAILURE_MESSAGES.get(handled)
            keep = None
            if fetch_failure is not None:
                code, level = fetch_failure
                keep = code
                record_system_message(
                    timeseries[0].dataset,
                    code,
                    _fetch_failure_message(
                        timeseries[0].dataset,
                        timeseries[0].constraints,
                        handled,
                        error,
                    ),
                    level=level,
                    constraint_group=constraint_group,
                    context={
                        # dataset/server are here so promql.query_for can rebuild the query
                        # from context alone, without a DB round trip.
                        "dataset": timeseries[0].dataset.name,
                        "server": str(timeseries[0].dataset.server),
                        "constraints": timeseries[0].constraints,
                        "error": str(error),
                    },
                )

            outcome.set(handled or Outcome.UNKNOWN_ERROR)
            if handled:
                # A recognised outcome, benign or not, means whatever else was previously
                # wrong with this dataset+group is no longer the failure mode in effect.
                _resolve_stale_fetch_failures(
                    timeseries[0].dataset,
                    constraint_group,
                    FETCH_FAILURE_CODES,
                    keep=keep,
                )
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

        # Row count separates "answered with data" from "answered with nothing" -- previously
        # only a warning with its context commented out. Per-series save failures below don't
        # fold into this outcome: the fetch itself succeeded; those surface via buoybarn.log.records.
        rows = len(timeseries_df)
        outcome.set(Outcome.SUCCESS if rows else Outcome.EMPTY_DATAFRAME, rows=rows)

        # The fetch succeeded, so any outstanding fetch failure (or backoff) for this
        # dataset+group is over; otherwise the list of outstanding messages only ever grows.
        _resolve_stale_fetch_failures(
            timeseries[0].dataset,
            constraint_group,
            RESOLVED_ON_SUCCESS,
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

                # Only clear end_time when the new data is actually newer than it, so a
                # dataset reload that returns the same old rows does not un-retire a series.
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
                    # This un-retirement resolves the retirement message that caused it
                    # (whatever constraint group recorded it), clearing end_time has no single
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
            failing_group = metrics.constraint_group_id(dict(constraints))
            record_system_message(
                dataset,
                SystemMessage.Code.BACKOFF_INCREASED,
                (
                    f"Backing off after a timeout on constraint group {failing_group}: the "
                    "per-request delay for the rest of this dataset's run increased from "
                    f"{request_refresh_time_seconds}s to {new_request_refresh_time_seconds}s. "
                    "This increase is per-run only -- it is discarded when this task ends, so "
                    "there is nothing persisted to look for here in the admin."
                ),
                level=SystemMessage.Level.WARNING,
                constraint_group=failing_group,
                context={
                    # `server` rather than `dataset`: backoff is a property of the server
                    # being slow, so this message links to the request-duration histogram
                    # for the server.
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
