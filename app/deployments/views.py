from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ParseError
from rest_framework.response import Response

from . import tasks
from .models import ErddapDataset, ErddapServer, Platform, TimeSeries
from .serializers import (
    ErddapDatasetSerializer,
    ErddapServerSerializer,
    PlatformSerializer,
)


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
        Prefetch(
            "timeseries_set",
            queryset=TimeSeries.objects.filter(active=True).prefetch_related(
                "dataset",
                "dataset__server",
                "data_type",
                "buffer_type",
            ),
            to_attr="timeseries_active",
        ),
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

    def dataset(self, **kwargs) -> ErddapDataset:
        """Retrieve the dataset from the request kwargs"""
        pk = kwargs["pk"]

        try:
            server, dataset = pk.split("-", maxsplit=1)
        except ValueError:
            raise ParseError(
                detail="Invalid server-dataset key. Server and dataset must be split by `-`.",
            )

        dataset = get_object_or_404(self.queryset, name=dataset, server__name=server)
        return dataset

    def retrieve(self, request, *args, **kwargs):  # pylint: disable=unused-argument
        dataset = self.dataset(**kwargs)
        serializer = self.serializer_class(dataset, context={"request": request})
        return Response(serializer.data)

    @action(detail=True)
    def refresh(self, request, **kwargs):
        dataset = self.dataset(**kwargs)

        tasks.single_refresh_dataset.delay(dataset.id, healthcheck=True)

        serializer = self.serializer_class(dataset, context={"request": request})
        return Response(serializer.data)

    @action(detail=True)
    def platforms(self, request, **kwargs):
        """Show the platforms with active timeseries for the specified dataset"""
        dataset = self.dataset(**kwargs)

        qs = (
            Platform.objects.filter(active=True, timeseries__dataset=dataset)
            .prefetch_related(
                "programattribution_set",
                "programattribution_set__program",
                "alerts",
                "programs",
                Prefetch(
                    "timeseries_set",
                    queryset=TimeSeries.objects.filter(active=True).prefetch_related(
                        "dataset",
                        "dataset__server",
                        "data_type",
                        "buffer_type",
                    ),
                    to_attr="timeseries_active",
                ),
            )
            .all()
        )

        serializer = PlatformSerializer(qs, many=True)

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

        tasks.single_refresh_server.delay(server.id, healthcheck=True)

        serializer = self.serializer_class(server, context={"request": request})
        return Response(serializer.data)

    @action(detail=True)
    def platforms(self, request, **kwargs):
        """Show platforms with active timeseries for the specified server"""
        pk = kwargs["pk"]
        server, dataset = pk.split("-")

        qs = (
            Platform.objects.filter(active=True, timeseries__dataset__server=pk)
            .prefetch_related(
                "programattribution_set",
                "programattribution_set__program",
                "alerts",
                "programs",
                Prefetch(
                    "timeseries_set",
                    queryset=TimeSeries.objects.filter(active=True).prefetch_related(
                        "dataset",
                        "dataset__server",
                        "data_type",
                        "buffer_type",
                    ),
                    to_attr="timeseries_active",
                ),
            )
            .all()
        )

        serializer = PlatformSerializer(qs, many=True)

        return Response(serializer.data)


class ProxyTimeout(APIException):
    status_code = 504
    default_detail = (
        f"Upstream ERDDAP server did not respond within {settings.PROXY_TIMEOUT_SECONDS}"
        " seconds, so the request timed out."
    )
    default_code = "erddap_timeout"


@cache_page(settings.PROXY_CACHE_SECONDS)
def server_proxy(request: HttpRequest, server_id: int) -> HttpResponse:
    server = ErddapServer.objects.get(id=server_id)
    path = request.get_full_path().split("proxy/")[1]

    request_url = urljoin(server.base_url + "/", path)

    try:
        response = requests.get(
            request_url,
            stream=True,
            timeout=settings.PROXY_TIMEOUT_SECONDS,
        )
    except requests.Timeout as e:
        raise ProxyTimeout from e

    return StreamingHttpResponse(
        response.raw,
        content_type=response.headers.get("content-type"),
        status=response.status_code,
        reason=response.reason,
    )
