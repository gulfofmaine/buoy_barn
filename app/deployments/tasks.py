from datetime import date, datetime, timedelta, timezone
import logging

from celery import shared_task
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
        try:
            if error.response.status_code == 403:
                logger.error(
                    f"403 error loading dataset {timeseries[0].dataset.name}. "
                    + "NOAA Coastwatch most likely blacklisted us. "
                    + "Try running the request manually from the worker pod to replicate the error and access the returned text."
                    + error,
                    extra={
                        "timeseries": timeseries,
                        "constraints": timeseries[0].constraints,
                    },
                    exc_info=True,
                )
                return

            elif error.response.status_code == 404:
                logger.warning(
                    f"No rows found for {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}: {error}",
                    extra={
                        "timeseries": timeseries,
                        "constraints": timeseries[0].constraints,
                    },
                    exc_info=True,
                )
                return

            elif error.response.status_code == 500:
                url = error.request.url

                response_500 = requests.get(url)

                if "nRows = 0" in response_500.text:
                    logger.info(
                        f"500 error loading {timeseries[0].dataset.name} with constraint {timeseries[0].constraints} because there are no matching rows"
                    )
                    return

                if "is outside of the variable" in response_500.text:
                    try:
                        times_str = response_500.text.rpartition("actual_range:")[
                            -1
                        ].rpartition(")")[0]
                    except AttributeError as e:
                        logger.warning(
                            f"Unable to access attribute of out of data dataset {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}",
                            extra={
                                "timeseries": timeseries,
                                "constraints": timeseries[0].constraints,
                            },
                            exc_info=True,
                        )
                        return

                    times = []
                    for potential_time in times_str.split(" "):
                        try:
                            time = parse_time_string(potential_time)
                            times.append(time[0])
                        except DateParseError:
                            pass
                    times.sort(reverse=True)

                    try:
                        end_time = times[0]
                    except IndexError:
                        logger.warning(f"Unable to parse datetimes in error")
                        return

                    offset = timezone(timedelta(hours=0))
                    week_ago = datetime.now(offset) - timedelta(days=7)

                    if end_time < week_ago:
                        # set end time for timeseries
                        for ts in timeseries:
                            ts.end_time = end_time
                            ts.save()

                            logger.warning(
                                f"Set end time for {ts} to {end_time} based on responses from {url}",
                                extra={"timeseries": ts, "constraints": ts.constraints},
                                exc_info=True,
                            )

                    return

                logger.info(
                    f"500 error loading dataset {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}: {error} ",
                    extra={
                        "timeseries": timeseries,
                        "constraints": timeseries[0].constraints,
                        "error_body": response_500.text,
                    },
                    exc_info=True,
                )
                return

            logger.error(
                f"{error.response.status_code} error loading dataset {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}: {error}",
                extra={
                    "timeseries": timeseries,
                    "constraints": timeseries[0].constraints,
                },
                exc_info=True,
            )
            return

        except AttributeError:
            logger.error(
                f"Error loading dataset {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}: {error}",
                extra={
                    "timeseries": timeseries,
                    "constraints": timeseries[0].constraints,
                },
                exc_info=True,
            )
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
            value = row[series.variable]

            if isinstance(value, Timedelta):
                logger.info("Converting from Timedelta to seconds")
                value = value.seconds

            series.value = value
            series.value_time = row["time"].to_pydatetime()
            series.save()
        except TypeError as error:
            logger.error(f"Could not save {series.variable} from {row}", exc_info=True)


@shared_task
def refresh_dataset(dataset_id: int, healthcheck: bool = False):
    """ Refresh the values for all timeseries associated with a specific dataset 
    
    Params:
        dataset_id (int): Primary key of ErddapDataset to refresh all timeseries for
        healthcheck (bool): Should Healthchecks.io be signaled when the dataset has completed updating?
    """
    dataset = ErddapDataset.objects.get(pk=dataset_id)

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
