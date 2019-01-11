from forecasts.forecasts.base_forecast import ForecastTypes
from forecasts.forecasts.neracoos_erddap.base_neracoos_erddap_forecast import (
    BaseNERACOOSERDDAPForecast,
)


class BaseBedfordForecast(BaseNERACOOSERDDAPForecast):
    dataset = "WW3_72_GulfOfMaine_latest"
    source_url = "http://www.neracoos.org/erddap/griddap/WW3_72_GulfOfMaine_latest.html"


class BedfordWaveHeight(BaseBedfordForecast):
    slug = "bedford_ww3_wave_height"
    name = "Bedford Institute Wave Model - Height"
    description = "Wave Height from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_HEIGHT

    field = "hs"


class BedfordWavePeriod(BaseBedfordForecast):
    slug = "bedford_ww3_wave_period"
    name = "Bedford Institute Wave Model - Height"
    description = "Wave Height from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_PERIOD

    field = "fp"


class BedfordWaveDirection(BaseBedfordForecast):
    slug = "bedford_ww3_wave_direction"
    name = "Bedford Institute Wave Model - Direction"
    description = "Wave Direction from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_DIRECTION

    field = "dir"
