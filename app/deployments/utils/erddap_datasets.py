from datetime import datetime, timedelta
from logging import getLogger
import os
from typing import List

from erddapy import ERDDAP
from pandas import DataFrame


logger = getLogger(__name__)


def filter_dataframe(df: DataFrame, column: str) -> DataFrame:
    """ Remove invalid times and for the specified column"""
    df = df[df["time (UTC)"].notna()]
    column_name = [col for col in df.columns if col.split(" ")[0] == column][0]
    return df[df[column_name].notna()]


def setup_variables(
    server: ERDDAP,
    dataset: str,
    variables: List[str],
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


def retrieve_dataframe(server, dataset: str, constraints, timeseries) -> DataFrame:
    e = setup_variables(
        server.connection(),
        dataset,
        list(set(series.variable for series in timeseries)),
        constraints=constraints,
    )

    e.requests_kwargs["timeout"] = float(
        os.environ.get("RETRIEVE_DATAFRAME_TIMEOUT_SECONDS", 60)
    )

    return e.to_pandas(parse_dates=True)
