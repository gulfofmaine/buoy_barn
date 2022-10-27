import os
from datetime import datetime
from json import JSONDecodeError

# from memoize import memoize
import pandas as pd
import requests
import sentry_sdk
from erddapy import ERDDAP

from forecasts.forecasts.base_forecast import BaseForecast
from forecasts.utils import erddap as erddap_utils

# from requests import HTTPError


class BaseERDDAPForecast(BaseForecast):
    """Extends BaseForecast with methods for accessing and retrieving forecasts from ERDDAP servers

    Attributes:
        server (str): ERDDAP server URL without trailing slash
        dataset (str): Dataset Id (for example: N01_aanderaa_all)
        to_360 (bool): Does the longitude of the dataset go from 0 - 360 instead of from -180 to 180
        field (str): Dataset variable name
    """

    server: str = NotImplemented
    dataset: str = NotImplemented
    to_360: bool = False
    field: str = NotImplemented

    def point_forecast(self, lat: float, lon: float) -> list[tuple[datetime, float]]:
        """Retrieve and return a formatted forecast for given latitude and longitude.

        Can be overridded for datasets that have multiple fields or other extra computation needed.

        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East

        Returns:
            List of tuples of forecasted times and values
        """
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

    def json(self):
        """Returns a dict with standard information about the forecast"""
        return {
            **super().json(),
            "server": self.server,
            "dataset": self.dataset,
            "to_360": self.to_360,
            "field": self.field,
        }

    def offset_value(self, value: float) -> float:  # pylint: disable=no-self-use
        """Allows you to override a value to return something more helpful
        (say Celsius rather than Kelvin)"""
        return value

    def connection(self) -> ERDDAP:
        """Return a connection to the ERDDAP server"""
        conn = ERDDAP(self.server)
        conn.dataset_id = self.dataset

        return conn

    def request_dataset(self, lat: float, lon: float):
        """Return the dataset JSON table dict for a given latitude and longitude

        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East

        Returns:
            Table object from ERDDAP dataset for a given latitude and longitude
        """
        sentry_sdk.set_tag("forecast_dataset_id", self.dataset)
        url = self.dataset_url(lat, lon)
        timeout = float(os.environ.get("RETRIEVE_FORECAST_TIMEOUT_SECONDS", 60))
        response = requests.get(url, timeout=timeout)
        try:
            return response.json()["table"]
        except JSONDecodeError as e:
            raise JSONDecodeError(
                f"Error decoding JSON from {url}: {e}",
                doc=e.doc,
                pos=e.pos,
            ) from e

    def dataset_info_df(self) -> pd.DataFrame:
        """Retrieve the most recent metadata for a dataset to find valid time and coordinates

        Returns:
            Pandas DataFrame
        """
        conn = self.connection()

        info_csv_url = conn.get_info_url(response="csv")

        return pd.read_csv(info_csv_url)

    def dataset_url(self, lat: float, lon: float) -> str:
        """Return the full url of the dataset with query string for a given latitude and longitude.

        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East

        Returns:
            Dataset URL
        """
        return f"{self.server}/griddap/{self.dataset}.json?{self.dataset_query_string(lat, lon)}"

    def dataset_query_string(self, lat: float, lon: float) -> str:
        """Create the query string for a dataset

        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East

        Returns:
            Query string for dataset with variables, times, and coordinates
        """
        info_df = self.dataset_info_df()

        return ",".join(
            f"{variable}{self.coverage_time_str(info_df)}{self.coordinates_str(info_df, lat, lon)}"
            for variable in self.request_variables()
        )

    def coverage_time_str(
        self,
        info_df=pd.DataFrame,
    ) -> str:  # pylint: disable=no-self-use
        """Formatted query string element for forecast coverage time range

        Args:
            info_df (pd.DataFrame): Pandas DataFrame
        """
        return erddap_utils.coverage_time_str(info_df)

    def request_variables(self) -> list[str]:
        """The variables that should be requested from the dataset.
        Can be overridden for more complicated datasets that require multiple fields

        Returns:
            List of ERDDAP variable strings
        """
        return [self.field]

    def coordinates_str(self, info_df: pd.DataFrame, lat: float, lon: float) -> str:
        """Create coordinates query string element

        Arguments:
            info_df(pd.DataFrame): Dataset metadata DataFrame
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East
        """
        if self.to_360:
            lon_value = 360 + lon
        else:
            lon_value = lon

        return erddap_utils.coordinates_str(info_df, lat, lon_value)
