from datetime import datetime, timedelta
from logging import getLogger
from typing import List

from erddapy import ERDDAP
from pandas import DataFrame
import pandas as pd


logger = getLogger(__name__)


def filter_dataframe(df: DataFrame, column: str) -> DataFrame:
    """ Remove invalid times and for the specified column"""
    df = df[df['time'].notna()]
    return df[df[column].notna()]


def setup_variables(server: ERDDAP, dataset: str, variables: List[str], constraints=None, time: datetime = None) -> ERDDAP:
    server.dataset_id = dataset
    server.response = 'nc'
    server.protocol = 'tabledap'

    if not constraints:
        constraints = {}

    if not time:
        time = datetime.utcnow() - timedelta(hours=24)
    
    constraints['time>='] = time
    server.constraints = constraints

    server.variables = ['time'] + variables

    return server


def retrieve_dataframe(server, dataset: str, constraints, timeseries) -> DataFrame:
    e = setup_variables(server.connection(), 
                        dataset, 
                        list(set(series.variable for series in timeseries)),
                        constraints=constraints)

    ds = e.to_xarray()
    return ds.to_dataframe()
