from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from deployments import standard_names
from deployments.models import TimeSeries
from deployments.utils.erddap_datasets import TIME_COLUMN, VALUE_COLUMN


def encode_value(value):  # noqa: PLR0911
    """Make Pandas and Numpy values json serializable"""
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, pd.Timestamp | datetime):
        return value.isoformat()
    if isinstance(value, list | np.ndarray | pd.Series):
        return [encode_value(v) for v in value]
    if isinstance(value, dict):
        return {encode_value(k): encode_value(v) for k, v in value.items()}
    try:
        if pd.isna(value):
            return None
    except ValueError as e:
        raise ValueError(f"Unable to encode value {value}") from e
    return value


def extrema_for_timeseries(ts: TimeSeries, df: pd.DataFrame) -> dict:
    """
    Calculate the extrema for a timeseries
    """
    extrema_df = df
    extrema_df = df.set_index(TIME_COLUMN)

    column_name = VALUE_COLUMN

    try:
        extrema = {
            "max": {
                "time": extrema_df[column_name].idxmax(),
                "value": extrema_df[column_name].max(),
            },
            "min": {
                "time": extrema_df[column_name].idxmin(),
                "value": extrema_df[column_name].min(),
            },
        }
    except KeyError as e:
        raise KeyError(f"Unable to find {ts.variable} in {extrema_df.columns}") from e

    if ts.data_type.standard_name in standard_names.WATER_LEVEL:
        tides_df = tidal_extrema(extrema_df, column_name)
        extrema["tides"] = tides_df.to_dict(orient="records")

    return encode_value(extrema)


def tidal_extrema(
    df: pd.DataFrame,
    water_level_column: str,
    time_col: str = TIME_COLUMN,
) -> pd.DataFrame:
    """Calculate the high and low tides for a timeseries"""
    # Hannah suggested a minimum distance of ten hours between tides,
    # but we need to specifiy the number of values
    # pandas <2 doesn't allow .diff() on index
    min_distance = timedelta(hours=10) / df.reset_index()[time_col].diff().mean()

    high_idx = find_peaks(df[water_level_column], distance=min_distance)
    low_idx = find_peaks(-df[water_level_column], distance=min_distance)

    high_tides = df.iloc[high_idx[0]]
    high_tides.loc[:, "tide"] = "high"

    low_tides = df.iloc[low_idx[0]]
    low_tides.loc[:, "tide"] = "low"

    tides_df = pd.concat([high_tides, low_tides])
    tides_df = tides_df.sort_index().reset_index()

    tides_df[time_col] = tides_df[time_col].map(lambda x: x.isoformat())
    tides_df = tides_df[["time", "value", "tide"]]

    return tides_df
