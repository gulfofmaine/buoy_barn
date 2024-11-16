from datetime import UTC, datetime, timedelta
from logging import getLogger

from erddapy import ERDDAP
from pandas import DataFrame

from ..models import ErddapServer, TimeSeries

logger = getLogger(__name__)


def filter_dataframe(df_to_filter: DataFrame, column: str) -> DataFrame:
    """Remove invalid times and for the specified column"""
    filtered_df = df_to_filter[df_to_filter["time (UTC)"].notna()]
    column_name = [col for col in filtered_df.columns if col.split(" ")[0] == column][0]
    return filtered_df[filtered_df[column_name].notna()]


def setup_variables(  # noqa: PLR0913
    server: ERDDAP,
    dataset: str,
    variables: list[str],
    constraints=None,
    time: datetime = None,
    forecast: bool = False,
) -> ERDDAP:
    """Configure ERDDAP variable for requests.

    Will default to the last 24 hours if time isn't specified, unless it is a
    forecast/prediction then it will fetch the next 7 days.
    """
    server.dataset_id = dataset
    server.response = "nc"
    server.protocol = "tabledap"

    constraints = {} if not constraints else constraints.copy()

    if time:
        constraints["time>="] = time
    elif forecast:
        constraints["time>="] = datetime.now(UTC)
        constraints["time<="] = datetime.now(UTC) + timedelta(days=7)
    else:
        constraints["time>="] = datetime.now(UTC) - timedelta(hours=24)

    server.constraints = constraints

    server.variables = ["time"] + variables

    return server


def retrieve_dataframe(
    server: ErddapServer,
    dataset: str,
    constraints,
    timeseries: list[TimeSeries],
) -> DataFrame:
    """Returns a dataframe from ERDDAP for a given dataset

    Attempts to sort the dataframe by time
    """
    forecast = any(
        ts.timeseries_type in TimeSeries.FUTURE_TYPES
        for ts in timeseries
    )
    e = setup_variables(
        server.connection(),
        dataset,
        list({series.variable for series in timeseries}),
        constraints=constraints,
        forecast=forecast,
    )

    timeout_seconds = server.request_timeout_seconds
    e.requests_kwargs["timeout"] = timeout_seconds

    erddap_df = e.to_pandas(parse_dates=True)

    try:
        erddap_df = erddap_df.sort_values("time (UTC)")
    except KeyError:
        logger.warning(f"Unable to sort dataframe by `time (UTC)` for {dataset}")

    return erddap_df
