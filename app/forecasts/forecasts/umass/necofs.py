""" UMass NECOFS wave forecasts """
from forecasts.forecasts.base_forecast import ForecastTypes
from forecasts.forecasts.base_stac_edr_forecast import BaseSTACEDRForecast

NECOFS_CATALOG_URL = (
    "http://www.smast.umassd.edu:8080/"
    "thredds/forecasts.html?dataset=necofs_gom3_wave"
)


class BaseNECOFSForecast(BaseSTACEDRForecast):
    """NECOFS FVCOM dataset info"""

    source_url = NECOFS_CATALOG_URL
    source_collection_url = (
        "https://data.neracoos.org/stac/FVCOM_GOM3_WAVE/collection.json"
    )
    date_pattern = "FVCOM_GOM3_Wave_%Y%m%d%H"


class NecofsWaveHeight(BaseNECOFSForecast):
    """NECOFS wave height forecast"""

    slug = "necofs_wave_height"
    name = "Northeast Coastal Ocean Forecast System - Wave Height"
    description = "Wave Height from the Northeast Coastal Ocean Forecast System"
    forecast_type = ForecastTypes.SIGNIFICANT_WAVE_HEIGHT
    units = "meters"

    field = "hs"


class NecofsWavePeriod(BaseNECOFSForecast):
    """NECOFS wave period forecast"""

    slug = "necofs_wave_period"
    name = "Northeast Coastal Ocean Forecast System - Wave Period"
    description = "Wave Period from the Northeast Coastal Ocean Forecast System"
    forecast_type = ForecastTypes.WAVE_PERIOD
    units = "seconds"

    field = "tpeak"


class NecofsWaveDirection(BaseNECOFSForecast):
    """NECOFS wave direction forecast"""

    slug = "necofs_wave_direction"
    name = "Northeast Coastal Ocean Forecast System - Wave From Direction"
    description = "Wave Direction from the Northeast Coastal Ocean Forecast System"
    forecast_type = ForecastTypes.WAVE_DIRECTION
    units = "degree"

    field = "wdir"
