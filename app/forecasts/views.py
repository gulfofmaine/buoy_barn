"""Viewset for displaying forecasts, and fetching point forecast data is lat,lon are specified"""
import logging
from datetime import timezone
from json import JSONDecodeError

from rest_framework import viewsets
from rest_framework.exceptions import APIException, NotFound
from rest_framework.response import Response

from forecasts.forecasts import forecast_list
from forecasts.serializers import ForecastSerializer

logger = logging.getLogger(__name__)


class ForecastViewSet(viewsets.ViewSet):
    """A viewset for forecasts"""

    def list(self, request):  # pylint: disable=no-self-use,unused-argument
        """List all forecasts"""
        serializer = ForecastSerializer(forecast_list, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):  # pylint: disable=no-self-use
        """Display a detail endpoint with point forecast information if lat, lon are given"""
        filtered = [forecast for forecast in forecast_list if forecast.slug == pk]
        try:
            forecast = filtered[0]
        except IndexError:
            logger.warning(f"Unknown forecast slug: {pk}")
            raise NotFound(detail=f"Unknown forecast slug: {pk}")
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
            try:
                time_series = forecast.point_forecast(lat, lon)
            except JSONDecodeError as error:
                logger.error(
                    f"Error retrieving dataset due to a JSON decode error: {error}",
                    exc_info=True,
                )
                raise APIException(
                    detail=f"Error retrieving dataset for forecast slug: {pk}",
                )
            except ConnectionError as error:
                if "Connection timed out" in str(error):
                    logger.info(f"Upstream forecast timed out: {error}")
                    raise APIException(
                        detail=f"Upstream forecast source timed out for forecast: {pk}",
                    )

                logger.error(
                    f"ConnectionError (probably a timeout): {error}",
                    exc_info=True,
                )
                raise APIException(
                    detail=f"Error retrieving dataset for forecast slug: {pk}",
                )

            data["time_series"] = [
                {"time": time.replace(tzinfo=timezone.utc), "reading": reading}
                for time, reading in time_series
            ]

        else:
            data["time_series"] = "No `lat` and/or `lon` parameter specified"

        return Response(data)
