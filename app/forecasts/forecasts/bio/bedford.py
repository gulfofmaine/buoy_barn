"""Bedford Institute forecasts"""
from forecasts.forecasts.base_forecast import ForecastTypes
from forecasts.forecasts.base_stac_edr_forecast import BaseSTACEDRForecast


class BaseBedfordForecast(BaseSTACEDRForecast):
    """Bedford dataset information"""

    source_url = "http://www.neracoos.org/erddap/griddap/WW3_72_GulfOfMaine_latest.html"
    source_collection_url = "https://data.neracoos.org/stac/WW3_72_GulfOfMaine/collection.json"
    date_pattern = "WW3_72_GulfOfMaine_%Y%m%d%H"


class BedfordWaveHeight(BaseBedfordForecast):
    """Bedford wave height forecast"""

    slug = "bedford_ww3_wave_height"
    name = "Bedford Institute Wave Model - Height"
    description = "Wave Height from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.SIGNIFICANT_WAVE_HEIGHT
    units = "meters"

    field = "hs"


class BedfordWavePeriod(BaseBedfordForecast):
    """Bedford wave period forecast"""

    slug = "bedford_ww3_wave_period"
    name = "Bedford Institute Wave Model - Period"
    description = "Wave Period from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_PERIOD
    units = "seconds"

    field = "t01"


class BedfordWaveDirection(BaseBedfordForecast):
    """Bedford wave direction forecast"""

    slug = "bedford_ww3_wave_direction"
    name = "Bedford Institute Wave Model - Wave From Direction"
    description = "Wave Direction from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_DIRECTION
    units = "degrees"

    field = "dir"
