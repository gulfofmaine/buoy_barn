import pandas as pd
import numpy as np

from deployments.models import TimeSeries
from deployments import standard_names

def extrema_for_timeseries(ts: TimeSeries, df: pd.DataFrame) -> dict:
    """
    Calculate the extrema for a timeseries
    """
    extrema_df = df
    extrema_df["time (UTC)"] = pd.to_datetime(extrema_df["time (UTC)"])
    extrema_df = df.set_index("time (UTC)")

    column_name = extrema_df.columns[0]

    try:
        extrema = {
            "max": {
                "time": extrema_df[column_name].idxmax().isoformat(),
                "value": extrema_df[column_name].max(),
            },
            "min": {
                "time": extrema_df[column_name].idxmin().isoformat(),
                "value": extrema_df[column_name].min(),
            }
        }
    except KeyError as e:
        raise KeyError(f"Unable to find {ts.variable} in {extrema_df.columns}") from e

    if ts.data_type.standard_name in standard_names.WATER_LEVEL:
        tides_df = tidal_extrema(extrema_df, column_name)
        extrema["tides"] = tides_df.to_dict(orient="records")

    return extrema



def tidal_extrema(df: pd.DataFrame, water_level_column: str, time_col: str = "time (UTC)") -> pd.DataFrame:
    """Calculate the high and low tides for a timeseries"""
    water_level_df = df.copy()

    cycle = water_level_df.groupby(pd.Grouper(freq=f"{12 * 60 + 25}min"))
    high_times = cycle.idxmax()
    low_times = cycle.idxmin()

    high_tides = water_level_df.loc[high_times[water_level_column]]
    high_tides["tide"] = "high"

    low_tides = water_level_df.loc[low_times[water_level_column]]
    low_tides["tide"] = "low"

    tides_df = pd.concat([high_tides, low_tides])
    tides_df = tides_df.sort_index()
    tides_df = tides_df.reset_index()

    tides_df[time_col] = tides_df[time_col].map(lambda x: x.isoformat())
    tides_df = tides_df.rename(columns={water_level_column: "value", time_col: "time"})

    return tides_df
