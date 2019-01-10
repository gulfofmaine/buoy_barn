from datetime import datetime
from typing import List, Tuple

from erddapy import ERDDAP

# from memoize import memoize
import pandas as pd
import requests
from requests import HTTPError

from forecasts.forecasts.base_forecast import BaseForecast
from forecasts.utils import erddap as erddap_utils


# http://www.neracoos.org/erddap/griddap/WW3_72_GulfOfMaine_latest.json?
# hs
# [(2019-01-10T12:00:00Z):1:(2019-01-10T12:00:00Z)]
# [(38.0):1:(46.0)][(-76.0):1:(-60.0)]


# https://coastwatch.pfeg.noaa.gov/erddap/griddap/NCEP_Global_Best.json?
# ugrd10m[(2019-01-07):1:(2019-01-10T12:00:00Z)][(45):1:(45)][(256):1:(256)],
# vgrd10m[(2019-01-07):1:(2019-01-10T12:00:00Z)][(45):1:(45)][(256):1:(256)]


class BaseERDDAPForecast(BaseForecast):
    server: str = NotImplemented
    dataset: str = NotImplemented
    to_360: bool = False
    field: str = NotImplemented

    def point_forecast(self, lat: float, lon: float) -> List[Tuple[datetime, float]]:
        json = self.request_dataset(lat, lon)

        column_names = json["columnNames"]

        time_index = column_names.index("time")
        field_index = column_names.index(self.field)

        rows = json["rows"]

        return [
            (
                erddap_utils.parse_time(row[time_index]),
                self.offset_value(row[field_index]),
            )
            for row in rows
        ]

    def offset_value(self, value: float) -> float:
        """ Allows you to override a value to return something more helpful (say Celsius rather than Kelvin) """
        return value

    def connection(self) -> ERDDAP:
        conn = ERDDAP(self.server)
        conn.dataset_id = self.dataset

        return conn

    def request_dataset(self, lat: float, lon: float):
        response = requests.get(self.dataset_url(lat, lon))
        return response.json()["table"]

    def dataset_info_df(self) -> pd.DataFrame:
        """ Current dataset info """
        conn = self.connection()

        info_csv_url = conn.get_info_url(response="csv")

        return pd.read_csv(info_csv_url)

    def dataset_url(self, lat: float, lon: float) -> str:
        return f"{self.server}/griddap/{self.dataset}.json?{self.dataset_query_string(lat, lon)}"

    def dataset_query_string(self, lat: float, lon: float) -> str:
        info_df = self.dataset_info_df()

        return ",".join(
            f"{variable}{self.coverage_time_str(info_df)}{self.coordinates_str(info_df, lat, lon)}"
            for variable in self.request_variables()
        )

    def coverage_time_str(self, info_df=pd.DataFrame) -> str:
        """ Formatted string for full forecast coverage range """
        return erddap_utils.coverage_time_str(info_df)

    def request_variables(self) -> List[str]:
        """ The variables that should be requested from the dataset """
        return [self.field]

    def coordinates_str(self, info_df: pd.DataFrame, lat: float, lon: float) -> str:
        if self.to_360:
            lon_value = 360 + lon
        else:
            lon_value = lon

        return erddap_utils.coordinates_str(info_df, lat, lon_value)
