import logging

from celery import shared_task
from requests import HTTPError
from sentry_sdk import capture_exception, capture_message

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
        capture_exception(error)
        logger.warning(
            f"No rows found for {timeseries[0].dataset.name} with constraint {timeseries[0].constraints}"
        )

    else:
        for series in timeseries:
            filtered_df = filter_dataframe(df, series.variable)

            try:
                row = filtered_df.iloc[-1]
            except IndexError:
                message = f"Unable to find position in dataframe for {series.platform.name} - {series.variable}"
                logger.warning(message)
                capture_message(message)
            else:
                try:
                    series.value = row[series.variable]
                    series.value_time = row["time"].to_pydatetime()
                    series.save()
                except TypeError as error:
                    logger.warning(f"Could not save {series.variable} from {row}")


@shared_task
def refresh_dataset(dataset_id: int):
    """ Refresh the values for all timeseries associated with a specific dataset """
    dataset = ErddapDataset.objects.get(pk=dataset_id)

    groups = dataset.group_timeseries_by_constraint()

    for constraints in groups:
        timeseries = groups[constraints]
        update_values_for_timeseries(timeseries)


@shared_task
def refresh_server(server_id: int):
    """ Refresh all the timeseries data for a server """
    server = ErddapServer.objects.get(pk=server_id)

    for ds in server.erddapdataset_set.all():
        refresh_dataset(ds.id)
