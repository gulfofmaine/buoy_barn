from datetime import datetime, timedelta
from logging import getLogger

from erddapy import ERDDAP
from pandas import DataFrame
import pandas as pd


logger = getLogger(__name__)


def filter_dataframe(df: DataFrame) -> DataFrame:
    for col in df.columns:
        df = df[df[col].notna()]
    
    return df[df['depth'] < 500]


def retrieve_dataframe(server, dataset: str, timeseries) -> DataFrame:
    e = server.connection()
    e.dataset_id = dataset
    e.response = 'nc'
    e.protocol = 'tabledap'

    yesterday = datetime.utcnow() - timedelta(hours=24)

    e.constraints = {
        'time>=': yesterday
    }

    e.variables = ['time', 'depth']
    e.variables += set(series.variable for series in timeseries)

    ds = e.to_xarray()
    return ds.to_dataframe()