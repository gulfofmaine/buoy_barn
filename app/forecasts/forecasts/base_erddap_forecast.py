from typing import List

from erddapy import ERDDAP

# from memoize import memoize
import pandas as pd
from requests import HTTPError

from forecasts.forecasts.base_forecast import BaseForecast


# http://www.neracoos.org/erddap/griddap/WW3_72_GulfOfMaine_latest.json?
# hs
# [(2019-01-10T12:00:00Z):1:(2019-01-10T12:00:00Z)]
# [(38.0):1:(46.0)][(-76.0):1:(-60.0)]


class BaseERDDAPForecast(BaseForecast):
    server: str = NotImplemented
    dataset: str = NotImplemented
    invertLongitude: bool = False
    field: str = NotImplemented

    def connection(self) -> ERDDAP:
        conn = ERDDAP(self.server)
        conn.dataset_id = self.dataset

        return conn

    def dataset_info_df(self) -> pd.DataFrame:
        """ Current dataset info """
        conn = self.connection()

        info_csv_url = conn.get_info_url(response="csv")

        return pd.read_csv(info_csv_url)

    # def latest_coverage_time(self) -> str:
    #     """ The latest time that is avaliable for a dataset """

    #     df = self.dataset_info_df()

    #     end = df[df["Attribute Name"] == "time_coverage_end"]["Value"]
    #     return end.values[0]

    def coverage_time_str(self) -> str:
        """ Formatted string for full forecast coverage range """
        df = self.dataset_info_df()

        start_series = df[df["Attribute Name"] == "time_coverage_start"]["Value"]
        start = start_series.values[0]

        end_series = df[df["Attribute Name"] == "time_coverage_end"]["Value"]
        end = end_series.values[0]

        return f"[({start}):1:({end})]"

    def request_variables(self) -> List[str]:
        """ The variables that should be requested from the dataset """
        return ["time", self.field]
