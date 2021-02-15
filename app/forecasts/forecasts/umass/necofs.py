""" UMass NECOFS wave forecasts """
from datetime import datetime
from typing import List, Tuple

from memoize import memoize
import numpy as np
import pandas as pd
import xarray as xr

from forecasts.forecasts.base_forecast import BaseForecast, ForecastTypes


NECOFS_THREDDS_URL = "http://www.smast.umassd.edu:8080/thredds/dodsC/FVCOM/NECOFS/Forecasts/NECOFS_WAVE_FORECAST.nc"
TIMEOUT_DAY_SECONDS = 24 * 60 * 60


def necofs_ds() -> xr.Dataset:
    """ Return an xarray Dataset for NECOFS """
    return xr.open_dataset(NECOFS_THREDDS_URL)


@memoize(timeout=TIMEOUT_DAY_SECONDS)
def necofs_node(lat: float, lon: float) -> int:
    """ Return the NECOFS Node index that is closest to the given lat, lon """
    ds = necofs_ds()
    distance = np.sqrt(((ds["lat"] - lat) ** 2) + ((ds["lon"] - lon) ** 2))
    return int(distance.argmin())


class BaseNecofsForecast(BaseForecast):
    """ Common base for NECOFS wave firecasts """

    source_url = NECOFS_THREDDS_URL
    field: str = NotImplemented

    def point_forecast(self, lat: float, lon: float) -> List[Tuple[datetime, float]]:
        node = necofs_node(lat, lon)

        ds = necofs_ds()

        dataarray = ds[self.field].isel(node=node)

        return [
            (pd.Timestamp(row.time.values), self.offset_value(row.data))
            for row in dataarray
        ]

    def offset_value(self, value: float) -> float:  # pylint: disable=no-self-use
        """ Allows you to override a value to return something more helpful (say Celsius rather than Kelvin) """
        return value


class NecofsWaveHeight(BaseNecofsForecast):
    """ NECOFS wave height forecast """

    slug = "necofs_wave_height"
    name = "Northeast Coastal Ocean Forecast System - Wave Height"
    description = "Wave Height from the Northeast Coastal Ocean Forecast System"
    forecast_type = ForecastTypes.SIGNIFICANT_WAVE_HEIGHT
    units = "meters"

    field = "hs"


class NecofsWavePeriod(BaseNecofsForecast):
    """ NECOFS wave period forecast """

    slug = "necofs_wave_period"
    name = "Northeast Coastal Ocean Forecast System - Wave Period"
    description = "Wave Period from the Northeast Coastal Ocean Forecast System"
    forecast_type = ForecastTypes.WAVE_PERIOD
    units = "seconds"

    field = "tpeak"


class NecofsWaveDirection(BaseNecofsForecast):
    """ NECOFS wave direction forecast """

    slug = "necofs_wave_direction"
    name = "Northeast Coastal Ocean Forecast System - Wave Direction"
    description = "Wave Direction from the Northeast Coastal Ocean Forecast System"
    forecast_type = ForecastTypes.WAVE_DIRECTION
    units = "degree"

    field = "wdir"
