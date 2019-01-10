from datetime import datetime
from enum import Enum
from typing import List, Tuple


class ForecastTypes(Enum):
    WAVE_HEIGHT = "waveHeight"
    WAVE_PERIOD = "wavePeriod"
    WAVE_DIRECTION = "waveDirection"
    AIR_TEMPERATURE = "airTemperature"
    WIND_SPEED = "windSpeed"
    WIND_DIRECTION = "windDirection"


class BaseForecast:
    """ Base type for forecasts.
    All forecasts must implement these attributes, 
    and the point_forecast method with the same signatures 
    as this is the interface that the API will interact with. """

    slug: str = NotImplemented
    forecast_type: ForecastTypes = NotImplemented
    name: str = NotImplemented
    description: str = NotImplemented
    source_url: str = NotImplemented

    def point_forecast(self, lat: float, lon: float) -> List[Tuple[datetime, float]]:
        raise NotImplementedError
