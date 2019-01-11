from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from forecasts.forecasts import forecast_list
from forecasts.serializers import ForecastSerializer


class ForecastViewSet(viewsets.ViewSet):
    """ A viewset for forecasts """

    def list(self, request):
        serializer = ForecastSerializer(forecast_list, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        filtered = [forecast for forecast in forecast_list if forecast.slug == pk]
        forecast = filtered[0]
        seralizer = ForecastSerializer(forecast)
        data = seralizer.data

        if "lat" in request.query_params:
            lat = float(request.query_params["lat"])
            data["latitude"] = lat
        else:
            data["latitude"] = "`lat` parameter not specified"

        if "lon" in request.query_params:
            lon = float(request.query_params["lon"])
            data["longitude"] = lon
        else:
            data["longitude"] = "`lon` parameter not specified"

        if "lat" in request.query_params and "lon" in request.query_params:
            time_series = forecast.point_forecast(lat, lon)

            data["time_series"] = [
                {"time": reading[0], "value": reading[1]} for reading in time_series
            ]

        else:
            data["time_series"] = "No `lat` and/or `lon` parameter specified"

        return Response(data)
