from rest_framework import viewsets
from rest_framework.response import Response

# from django.shortcuts import render

from forecasts.forecasts import forecast_list
from forecasts.serializers import ForecastSerializer

# Create your views here.


class ForecastViewSet(viewsets.ViewSet):
    """ A viewset for forecasts """

    def list(self, request):
        serializer = ForecastSerializer(forecast_list, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        filtered = [forecast for forecast in forecast_list if forecast.slug == pk]
        seralizer = ForecastSerializer(filtered[0])
        return Response(seralizer.data)
