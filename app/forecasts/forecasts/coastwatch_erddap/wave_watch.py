from forecasts.forecasts.base_forecast import ForecastTypes
from forecasts.forecasts.coastwatch_erddap.base_coastwatch import (
    BaseCoastWatchRDDAPForecast,
)


class BaseWaveWatch(BaseCoastWatchRDDAPForecast):
    dataset = "NWW3_Global_Best"
    source_url = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/NWW3_Global_Best.html"

    to_360 = True


class GlobalWaveWatchHeight(BaseWaveWatch):
    slug = "global_wave_watch_height"
    name = "Global Wave Watch III - Significant Wave Height"
    description = "Wave Height from the Global Wave Watch III model by the University of Hawaii"
    forecast_type = ForecastTypes.WAVE_HEIGHT

    field = "Thgt"
