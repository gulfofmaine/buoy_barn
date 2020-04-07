import logging

from celery import shared_task
from requests import HTTPError, Timeout
from pandas import Timedelta

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
        logger.warning(
            f"No rows found for {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}: {error}",
            extra={"timeseries": timeseries, "constraints": timeseries[0].constraints},
            exc_info=True
        )
    
    except Timeout as error:
        logger.warning(
            f"Timeout when trying to retrieve dataset {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}: {error}", 
            extra={"timeseries": timeseries, "constraints": timeseries[0].constraints},
            exc_info=True
        )
    
    except OSError as error:
        logger.error(
            f"Error loading dataset {timeseries[0].dataset.name} with constraints {timeseries[0].constraints}: {error}", 
            extra={"timeseries": timeseries, "constraints": timeseries[0].constraints},
            exc_info=True
        )

    else:
        for series in timeseries:
            filtered_df = filter_dataframe(df, series.variable)

            try:
                row = filtered_df.iloc[-1]
            except IndexError:
                message = f"Unable to find position in dataframe for {series.platform.name} - {series.variable}"
                logger.warning(message)
            else:
                try:
                    value = row[series.variable]

                    if isinstance(value, Timedelta):
                        logger.info("Converting from Timedelta to seconds")
                        value = value.seconds

                    series.value = value
                    series.value_time = row["time"].to_pydatetime()
                    series.save()
                except TypeError as error:
                    logger.error(
                        f"Could not save {series.variable} from {row}", exc_info=True
                    )


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
