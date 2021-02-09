import json

from deployments.tests.vcr import my_vcr
from forecasts.forecasts import forecast_list


@my_vcr.use_cassette("test_forecasts_api.yaml")
def test_forecasts_api(client):
    for forecast in forecast_list:
        print(forecast.slug)
        url = f"/api/forecasts/{forecast.slug}/?lat=43.7148&lon=-69.3578"
        response = client.get(url, format="json")

        for key in (
            "slug",
            "forecast_type",
            "name",
            "description",
            "source_url",
            "point_forecast",
            "units",
            "latitude",
            "longitude",
            "time_series",
        ):
            assert key in response.data

        assert "Z" in response.json()["time_series"][0]["time"]
