from datetime import datetime
from enum import Enum
from typing import List, Tuple


class ForecastTypes(Enum):
    WAVE_HEIGHT = "Wave Height"
    WAVE_PERIOD = "Wave Period"
    WAVE_DIRECTION = "Wave Direction"
    AIR_TEMPERATURE = "Air Temperature"
    WIND_SPEED = "Wind Speed"
    WIND_DIRECTION = "Wind Direction"


class BaseForecast:
    """ Base type for forecasts.
    All forecasts must implement these attributes,
    and the point_forecast method with the same signatures
    as this is the interface that the API will interact with.

    Attributes:
        slug (str): URL save slug (should be unique among forecasts)
        forecast_type (ForecastTypes): Type of forecast, so that the related datasets can also be loaded.
        name (str): Short name of forecast
        description (str): Longer description of forecast
        source_url (str): Website where a person can learn more about the forecast
        units (str): Units for the values that the forecast will return
    """

    slug: str = NotImplemented
    forecast_type: ForecastTypes = NotImplemented
    name: str = NotImplemented
    description: str = NotImplemented
    source_url: str = NotImplemented
    units: str = NotImplemented

    def point_forecast(self, lat: float, lon: float) -> List[Tuple[datetime, float]]:
        """ Method to override so that child forecasts can produce a forecast for a point of given latitude and longitude

        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East

        Returns:
            List of tuples of forecasted times and values
        """
        raise NotImplementedError

    def json(self):
        """ Returns a dict with standard information about the forecast """
        return {
            "slug": self.slug,
            "forecast_type": self.forecast_type,
            "name": self.name,
            "description": self.description,
            "source_url": self.source_url,
            "units": self.units
        }

    def __repr__(self):
        return f"<Forecast: {self.json()}>"
