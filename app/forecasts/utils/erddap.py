from datetime import datetime
from typing import Union

from pandas import DataFrame


def attribute_value(info_df: DataFrame, attribute: str) -> Union[float, str, int]:
    """ Return the value of a single dataset attribute """
    row = info_df[info_df["Attribute Name"] == attribute].values[0]
    value = row[-1]
    value_type = row[-2]
    if value_type == "int":
        return int(value)
    if value_type == "String":
        return value
    return float(value)


def coverage_time_str(info_df: DataFrame) -> str:
    start = attribute_value(info_df, "time_coverage_start")
    start_dt = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ")

    now = datetime.now()
    now = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if start_dt < now:
        start = now.isoformat() + "Z"
    end = attribute_value(info_df, "time_coverage_end")

    return f"[({start}):1:({end})]"


def coordinate_str(info_df: DataFrame, lat: float, lon: float) -> str:
    lat_precision = attribute_value(info_df, "geospatial_lat_resolution")
    lat_value = str(round_to(lat, lat_precision)).split(".")

    lon_precision = attribute_value(info_df, "geospatial_lon_resolution")
    lon_value = str(round_to(lon, lon_precision)).split(".")

    return (
        f"[({lat_value[0]}.{lat_value[1][:2]}):1:({lon_value[0]}.{lon_value[1][:2]})]"
    )


# From stack overflow answer https://stackoverflow.com/a/4265592
# to help with rounding coordinates
def round_to(n, precision):
    """ Round a value n to a precision """
    correction = 0.5 if n >= 0 else -0.5
    return int(n / precision + correction) * precision

