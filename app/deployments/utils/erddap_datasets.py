from datetime import UTC, datetime, timedelta
from logging import getLogger

import pandas as pd
from erddapy import ERDDAP

from ..models import ErddapServer, TimeSeries

logger = getLogger(__name__)


ERDDAP_TIME_COLUMN = "time (UTC)"
TIME_COLUMN = "time"
VALUE_COLUMN = "value"


def filter_dataframe(df_to_filter: pd.DataFrame, column: str) -> pd.DataFrame:
    """Remove invalid times and for the specified column, and renames time and value columns"""
    filtered_df = df_to_filter[df_to_filter[ERDDAP_TIME_COLUMN].notna()]
    column_name = [col for col in filtered_df.columns if col.split(" ")[0] == column][0]
    filtered_df = filtered_df[filtered_df[column_name].notna()]
    filtered_df = filtered_df[[ERDDAP_TIME_COLUMN, column_name]]
    filtered_df = filtered_df.rename(columns={column_name: VALUE_COLUMN, ERDDAP_TIME_COLUMN: "time"})
    filtered_df[TIME_COLUMN] = pd.to_datetime(filtered_df[TIME_COLUMN])
    return filtered_df


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
        constraints["time<="] = datetime.now(UTC)

    server.constraints = constraints

    server.variables = ["time"] + variables

    return server


def retrieve_dataframe(
    server: ErddapServer,
    dataset: str,
    constraints,
    timeseries: list[TimeSeries],
) -> pd.DataFrame:
    """Returns a dataframe from ERDDAP for a given dataset

    Attempts to sort the dataframe by time
    """
    forecast = any(ts.timeseries_type in TimeSeries.FUTURE_TYPES for ts in timeseries)
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
