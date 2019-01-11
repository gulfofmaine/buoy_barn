from dataclasses import dataclass
from datetime import datetime
from math import degrees, hypot, sin, sqrt
from typing import List, Tuple

from forecasts.forecasts.base_forecast import ForecastTypes
from forecasts.forecasts.coastwatch_erddap.base_coastwatch import (
    BaseCoastWatchRDDAPForecast,
)
from forecasts.utils import erddap as erddap_utils


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


@dataclass
class WindReading:
    """ Class for a wind measurement at a given time 
    
    Attributes:
        time (datetime): Time of forecasted value
        east (float): Wind component in m/s to the East
        north (float): Wind component in m/s to the North
    """

    time: datetime
    east: float
    north: float

    def speed(self) -> float:
        """ Return the speed of the wind in m/s """
        return hypot(self.east, self.north)

    def direction(self) -> float:
        """ Return the angle from North of the wind """
        return (360 + degrees(sin(self.north / self.east))) % 360


class BaseGFSWindForecast(BaseGFSForecast):
    """ The GFS forecast breaks down wind into two components, m/s to the East and the North.
    This means that we have to compute the direction and speed from those components, and retrieve both from the server

    Attributes:
        east_wind_field (str): ERDDAP dataset variable for the East component of the wind data
        north_wind_field (str): ERDDAP dataset variable for the North component of the wind data
    """

    east_wind_field = "ugrd10m"
    north_wind_field = "vgrd10m"

    def request_variables(self) -> List[str]:
        """ Return both the East and North wind fields to be requested """
        return [self.east_wind_field, self.north_wind_field]

    def time_series(self, lat: float, lon: float) -> List[WindReading]:
        """ Return a list of WindReadings for a given lat, lon forecast point 
        
        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East
        
        Returns:
            List of WindReading instances
        """
        json = self.request_dataset(lat, lon)

        columnNames = json["columnNames"]

        time_index = columnNames.index("time")
        east_index = columnNames.index(self.east_wind_field)
        north_index = columnNames.index(self.north_wind_field)

        rows = json["rows"]

        return [
            WindReading(row[time_index], row[east_index], row[north_index])
            for row in rows
        ]


class GFSWindSpeed(BaseGFSWindForecast):
    slug = "gfs_wind_speed"
    name = "NOAA/NCEP Global Forecast System - Wind Speed"
    description = "Wind Speed from NOAA/NCEP's Global Forecast System"
    forecast_type = ForecastTypes.WIND_SPEED

    def point_forecast(self, lat: float, lon: float) -> List[Tuple[datetime, float]]:
        """ Return a list of tuples for the wind speed 
        
        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East
        """
        readings = self.time_series(lat, lon)

        return [(reading.time, reading.speed()) for reading in readings]


class GFSWindDirection(BaseGFSWindForecast):
    slug = "gfs_wind_direction"
    name = "NOAA/NCEP Global Forecast System - Wind Direction"
    description = "Wind Direction from NOAA/NCEP's Global Forecast System"
    forecast_type = ForecastTypes.WIND_DIRECTION

    def point_forecast(self, lat: float, lon: float) -> List[Tuple[datetime, float]]:
        """ Return a list of tuples for the wind direction 
        
        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East
        """
        readings = self.time_series(lat, lon)

        return [(reading.time, reading.direction()) for reading in readings]
