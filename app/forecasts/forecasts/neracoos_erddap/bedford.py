"""Bedford Institute forecasts"""
from forecasts.forecasts.base_forecast import ForecastTypes
from forecasts.forecasts.neracoos_erddap.base_neracoos_erddap_forecast import (
    BaseNERACOOSERDDAPForecast,
)


class BaseBedfordForecast(BaseNERACOOSERDDAPForecast):
    """Bedford dataset information"""

    dataset = "WW3_72_GulfOfMaine_latest"
    source_url = "http://www.neracoos.org/erddap/griddap/WW3_72_GulfOfMaine_latest.html"


class BedfordWaveHeight(BaseBedfordForecast):
    """Bedford wave height forecast"""

    slug = "bedford_ww3_wave_height"
    name = "Bedford Institute Wave Model - Height"
    description = "Wave Height from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_HEIGHT
    units = "meters"

    field = "hs"


class BedfordWavePeriod(BaseBedfordForecast):
    """Bedford wave period forecast"""

    slug = "bedford_ww3_wave_period"
    name = "Bedford Institute Wave Model - Height"
    description = "Wave Height from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_PERIOD
    units = "seconds"

    field = "fp"


class BedfordWaveDirection(BaseBedfordForecast):
    """Bedford wave direction forecast"""

    slug = "bedford_ww3_wave_direction"
    name = "Bedford Institute Wave Model - Direction"
    description = "Wave Direction from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_DIRECTION
    units = "degrees"

    field = "dir"
