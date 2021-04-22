from urllib.parse import urljoin

from django.conf import settings
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
import requests
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Platform, ErddapDataset, ErddapServer
from .serializers import (
    PlatformSerializer,
    ErddapDatasetSerializer,
    ErddapServerSerializer,
)
from .tasks import refresh_dataset, refresh_server


@method_decorator(cache_page(60), name="list")
class PlatformViewset(viewsets.ReadOnlyModelViewSet):
    """
    A viewset for viewing Platforms
    """

    queryset = Platform.objects.filter(active=True).prefetch_related(
        "programattribution_set",
        "programattribution_set__program",
        "alerts",
        "programs",
    )
    serializer_class = PlatformSerializer

    def retrieve(self, request, *args, **kwargs):  # pylint: disable=unused-argument
        pk = kwargs["pk"]
        platform = get_object_or_404(self.queryset, name=pk)
        serializer = self.serializer_class(platform)
        return Response(serializer.data)


class DatasetViewSet(viewsets.ReadOnlyModelViewSet):
    """
    A viewset for viewing and triggering refreshed of datasets
    """

    queryset = ErddapDataset.objects.select_related("server")
    serializer_class = ErddapDatasetSerializer

    def retrieve(self, request, *args, **kwargs):  # pylint: disable=unused-argument
        pk = kwargs["pk"]

        server, dataset = pk.split("-", maxsplit=1)
        dataset = get_object_or_404(self.queryset, name=dataset, server__name=server)
        serializer = self.serializer_class(dataset, context={"request": request})
        return Response(serializer.data)

    @action(detail=True)
    def refresh(self, request, **kwargs):
        pk = kwargs["pk"]

        server, dataset = pk.split("-", maxsplit=1)
        dataset = get_object_or_404(self.queryset, name=dataset, server__name=server)

        refresh_dataset.delay(dataset.id, healthcheck=True)

        serializer = self.serializer_class(dataset, context={"request": request})
        return Response(serializer.data)


class ServerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    A viewset for viewing and triggering refreshes of all timeseries for a server
    """

    queryset = ErddapServer.objects
    serializer_class = ErddapServerSerializer

    @action(detail=True)
    def refresh(self, request, **kwargs):
        pk = kwargs["pk"]

        server = get_object_or_404(self.queryset, pk=pk)

        refresh_server.delay(server.id, healthcheck=True)

        serializer = self.serializer_class(server, context={"request": request})
        return Response(serializer.data)


@cache_page(settings.PROXY_CACHE_SECONDS)
def server_proxy(request: HttpRequest, server_id: int) -> HttpResponse:
    server = ErddapServer.objects.get(id=server_id)
    path = request.get_full_path().split("proxy/")[1]

    request_url = urljoin(server.base_url + "/", path)

    response = requests.get(request_url, stream=True)

    return StreamingHttpResponse(
        response.raw,
        content_type=response.headers.get("content-type"),
        status=response.status_code,
        reason=response.reason,
    )
