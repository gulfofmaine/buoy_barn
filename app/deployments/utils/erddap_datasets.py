from datetime import datetime, timedelta
from logging import getLogger

from erddapy import ERDDAP
from pandas import DataFrame

from ..models import ErddapServer

logger = getLogger(__name__)


def filter_dataframe(df: DataFrame, column: str) -> DataFrame:
    """Remove invalid times and for the specified column"""
    df = df[df["time (UTC)"].notna()]
    column_name = [col for col in df.columns if col.split(" ")[0] == column][0]
    return df[df[column_name].notna()]


def setup_variables(
    server: ERDDAP,
    dataset: str,
    variables: list[str],
    constraints=None,
    time: datetime = None,
) -> ERDDAP:
    server.dataset_id = dataset
    server.response = "nc"
    server.protocol = "tabledap"

    if not constraints:
        constraints = {}
    else:
        constraints = constraints.copy()

    if not time:
        time = datetime.utcnow() - timedelta(hours=24)

    constraints["time>="] = time
    server.constraints = constraints

    server.variables = ["time"] + variables

    return server


def retrieve_dataframe(
    server: ErddapServer,
    dataset: str,
    constraints,
    timeseries,
) -> DataFrame:
    """Returns a dataframe from ERDDAP for a given dataset

    Attempts to sort the dataframe by time"""
    e = setup_variables(
        server.connection(),
        dataset,
        list({series.variable for series in timeseries}),
        constraints=constraints,
    )

    e.requests_kwargs["timeout"] = server.request_timeout_seconds

    df = e.to_pandas(parse_dates=True)

    try:
        df = df.sort_values("time (UTC)")
    except KeyError:
        logger.warning(f"Unable to sort dataframe by `time (UTC)` for {dataset}")

    return df
