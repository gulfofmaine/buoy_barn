from forecasts.forecasts.base_forecast import ForecastTypes
from forecasts.forecasts.coastwatch_erddap.base_coastwatch import (
    BaseCoastWatchRDDAPForecast,
)


class BaseGFSForecast(BaseCoastWatchRDDAPForecast):
    dataset = "NCEP_Global_Best"
    source_url = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/NCEP_Global_Best.html"

    to_360 = True


class GFSAirTemp(BaseGFSForecast):
    slug = "gfs_air_temp"
    name = "NOAA/NCEP Global Forecast System - Air Temperature"
    description = "Air Temperature from NOAA/NCEP's Global Forecast System"
    forecast_type = ForecastTypes.AIR_TEMPERATURE

    field = "tmp2m"

    def offset_value(self, value: float) -> float:
        """ Offsets the fields native Kelvin to Celsius """
        return value - 273.15
