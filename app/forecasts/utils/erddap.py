"""ERDDAP dataset interaction utility functions"""
from datetime import datetime
from typing import Union

from pandas import DataFrame


def attribute_value(info_df: DataFrame, attribute: str) -> Union[float, str, int]:
    """Return the value of a single dataset attribute"""
    row = info_df[info_df["Attribute Name"] == attribute].values[0]
    value = row[-1]
    value_type = row[-2]
    if value_type == "int":
        return int(value)
    if value_type == "String":
        return value
    return float(value)


def coverage_time_str(info_df: DataFrame) -> str:
    """Create a coverage time URL string"""
    start = attribute_value(info_df, "time_coverage_start")
    start_dt = parse_time(start)

    now = datetime.now()
    now = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if start_dt < now:
        start = now.isoformat() + "Z"
    end = attribute_value(info_df, "time_coverage_end")

    return f"[({start}):1:({end})]"


def coordinates_str(info_df: DataFrame, lat: float, lon: float) -> str:
    """Return a string with coordinates formatted how ERDDAP expects"""
    lat_precision = attribute_value(info_df, "geospatial_lat_resolution")
    lat_value = str(round_to(lat, lat_precision)).split(".")

    lat_str = (
        f"[({lat_value[0]}.{lat_value[1][:2]}):1:({lat_value[0]}.{lat_value[1][:2]})]"
    )

    lon_precision = attribute_value(info_df, "geospatial_lon_resolution")
    lon_value = str(round_to(lon, lon_precision)).split(".")

    lon_str = (
        f"[({lon_value[0]}.{lon_value[1][:2]}):1:({lon_value[0]}.{lon_value[1][:2]})]"
    )

    return lat_str + lon_str


# From stack overflow answer https://stackoverflow.com/a/4265592
# to help with rounding coordinates
def round_to(n, precision):
    """Round a value n to a precision"""
    correction = 0.5 if n >= 0 else -0.5
    return int(n / precision + correction) * precision


def parse_time(dt: str) -> datetime:
    """Return a datetime object for an ERDDAP time

    ERDDAP time is in the format of 2019-01-10T00:00:00Z
    and it is nicer to use native datetimes for comparisons
    """
    return datetime.strptime(dt, "%Y-%m-%dT%H:%M:%SZ")
