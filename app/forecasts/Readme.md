# Forecasts

The forecast API is designed to allow access to various sources of point weather forecasts.
It is designed that it can be extended to pull forecasts from various sources on demand, and those sources can be extend.

## Using the API

To see the list of avaliable forecasts [localhost:8080/api/forecasts/](http://localhost:8080/api/forecasts/).

To retrieve a forecast for a point, take it's slug and append it to the end of the forecast path, and add a lat/lon parameter.

For example, if we wanted the Wave Watch 3 height forecast from the Bedford Institute, we would start by finding it's entry in the forecast list.

```json
{
  "slug": "bedford_ww3_wave_height",
  "forecast_type": "Wave Height",
  "name": "Bedford Institute Wave Model - Height",
  "description": "Wave Height from the Bedford Institute Wave Model",
  "source_url": "http://www.neracoos.org/erddap/griddap/WW3_72_GulfOfMaine_latest.html",
  "point_forecast": "/api/forecasts/bedford_ww3_wave_height/"
}
```

From this we can see it's url for retrieving a point forecast `"/api/forecasts/bedford_ww3_wave_height/"`.

To this, we can add query string parameters to specify latitude and longitude for a forecast `"?lat=43.629503&lon=-70.064824"` to get `"http://localhost:8080/api/forecasts/bedford_ww3_wave_height/?lat=43.629503&lon=-70.064824"`.

From that we will get our forecast details, and a time series for the forecasted value at the given point.

```json
{
  "slug": "bedford_ww3_wave_height",
  "forecast_type": "Wave Height",
  "name": "Bedford Institute Wave Model - Height",
  "description": "Wave Height from the Bedford Institute Wave Model",
  "source_url": "http://www.neracoos.org/erddap/griddap/WW3_72_GulfOfMaine_latest.html",
  "point_forecast": "/api/forecasts/bedford_ww3_wave_height/",
  "latitude": 43.629503,
  "longitude": -70.064824,
  "time_series": [
    {
      "time": "2019-01-11T00:00:00",
      "value": 0.33249047
    },
    {
      "time": "2019-01-11T01:00:00",
      "value": 0.5120419
    },
    {
      "time": "2019-01-11T02:00:00",
      "value": 0.60214335
    },
    {
      "time": "2019-01-11T03:00:00",
      "value": 0.67807496
    },
    {
      "time": "2019-01-11T04:00:00",
      "value": 0.71254003
    }
  ]
}
```

## Adding a new forecast

All forecasts need to implement a few attributes and a method in order to work with the API.

### Implementing required attributes and methods

The easiest way is to inherit from the [`BaseForecast`](forecasts/base_forecast.py) and implement all of it's attributes and method.

```python
# /app/forecasts/forecasts/base_forecast.py
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
    """

    slug: str = NotImplemented
    forecast_type: ForecastTypes = NotImplemented
    name: str = NotImplemented
    description: str = NotImplemented
    source_url: str = NotImplemented

    def point_forecast(self, lat: float, lon: float) -> List[Tuple[datetime, float]]:
        """ Method to override so that child forecasts can produce a forecast for a point of given latitude and longitude

        Args:
            lat (float): Latitude in degrees North
            lon (float): Longitude in degrees East

        Returns:
            List of tuples of forecasted times and values
        """
        raise NotImplementedError
```

As you can see, there are 5 attributes and one method that every forecast has to implement.

For forecasts from standard data server types, there may be an base forecast that already implements the `point_forecast` method, in exchange for adding a few more attributes.

For instance there is a base forecast for ERDDAP servers `BaseERDDAPForecast` in [`forecasts/forecasts/base_erddap_forecast.py`](forecasts/base_erddap_forecast.py).
Using `BaseERDDAPForecast`, most forecasts will be able to be implemented by setting a few attributes.

```python
# /app/forecasts/forecasts/neracoos_erddap/bedford.py
class BaseBedfordForecast(BaseNERACOOSERDDAPForecast):
    dataset = "WW3_72_GulfOfMaine_latest"
    source_url = "http://www.neracoos.org/erddap/griddap/WW3_72_GulfOfMaine_latest.html"


class BedfordWaveHeight(BaseBedfordForecast):
    slug = "bedford_ww3_wave_height"
    name = "Bedford Institute Wave Model - Height"
    description = "Wave Height from the Bedford Institute Wave Model"
    forecast_type = ForecastTypes.WAVE_HEIGHT

    field = "hs"
```

Here a wave height forecast is implemented with only 7 attributes.
Two of the attributes are implemented on a parent class as there are also wave period and direction forecasts avalaible from the same dataset.

To see a few more complicated ERDDAP forecasts which require multiple variables and extra computation, look at the [GFS forecast from CoastWatch](forecasts/coastwatch_erddap/gfs.py).

### Adding forecast to list of forecasts

In [forecasts/**init**.py](forecasts/__init__.py) there is a list of forecast instances.

Import your class, and instantiate it in the list.

```diff
...
+ from forecasts.forecasts.new_cool_forecast import AwesomeNewForecast

forecast_list = [
    BedfordWaveDirection(),
    BedfordWaveHeight(),
    BedfordWavePeriod(),
    GFSAirTemp(),
    GFSWindSpeed(),
    GFSWindDirection(),
+    AwesomeNewForecast(),
]
```
