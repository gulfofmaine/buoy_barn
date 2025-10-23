from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets

# from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import (
    action,  # , authentication_classes, permission_classes
)
from rest_framework.exceptions import APIException, ParseError

# from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import tasks
from .models import ErddapDataset, ErddapServer, Platform, TimeSeries
from .serializers import (  # TimeSeriesUpdateResponseSerializer,
    ErddapDatasetSerializer,
    ErddapServerSerializer,
    PlatformSerializer,
    TimeSeriesSerializer,
    TimeSeriesUpdateSerializer,
)


@method_decorator(cache_page(60), name="list")
class PlatformViewset(viewsets.ReadOnlyModelViewSet):
    """A viewset for viewing Platforms

    For a list queries, the platforms will be filtered by visibility.

    By default, only those where `visible_mariners=True` will be shown,
    but `visibility` can be set to `dev`, `graph_download` or `climatology`.
    """

    def get_platform_queryset(self, ts_active: bool = True):
        """Return the queryset for platforms with active timeseries"""
        ts_queryset = TimeSeries.objects.prefetch_related(
            "dataset",
            "dataset__server",
            "data_type",
            "buffer_type",
            "flood_levels",
        )

        if ts_active:
            ts_queryset = ts_queryset.filter(active=True, end_time__isnull=True)

        return Platform.objects.prefetch_related(
            "programattribution_set",
            "programattribution_set__program",
            "alerts",
            "programs",
            "links",
            Prefetch(
                "timeseries_set",
                queryset=ts_queryset,
                to_attr="timeseries_active",
            ),
        )

    serializer_class = PlatformSerializer

    def list(self, request, *args, **kwargs):  # pylint: disable=unused-argument
        visibility_key = request.query_params.get("visibility", "mariners").lower()
        if visibility_key not in {"mariners", "dev", "climatology", "graph_download"}:
            visibility_key = "mariners"
        filter_kwargs = {f"visible_{visibility_key}": True}

        ts_active = visibility_key not in {"graph_download", "climatology"}

        queryset = self.get_platform_queryset(ts_active=ts_active)
        queryset = self.filter_queryset(queryset).filter(**filter_kwargs)
        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):  # pylint: disable=unused-argument
        pk = kwargs["pk"]
        platform = get_object_or_404(self.get_platform_queryset(), name=pk)
        serializer = self.serializer_class(platform)
        return Response(serializer.data)


class DatasetViewSet(viewsets.ReadOnlyModelViewSet):
    """A viewset for viewing and triggering refreshed of datasets"""

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
            ) from None

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
            Platform.objects.filter(timeseries__dataset=dataset)
            .prefetch_related(
                "programattribution_set",
                "programattribution_set__program",
                "alerts",
                "programs",
                "links",
                Prefetch(
                    "timeseries_set",
                    queryset=TimeSeries.objects.filter(active=True).prefetch_related(
                        "dataset",
                        "dataset__server",
                        "data_type",
                        "buffer_type",
                        "flood_levels",
                    ),
                    to_attr="timeseries_active",
                ),
            )
            .all()
        )

        serializer = PlatformSerializer(qs, many=True)

        return Response(serializer.data)


class ServerViewSet(viewsets.ReadOnlyModelViewSet):
    """A viewset for viewing and triggering refreshes of all timeseries for a server"""

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
            Platform.objects.filter(timeseries__dataset__server=pk)
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


class TimeSeriesViewSet(viewsets.ReadOnlyModelViewSet):
    """A viewset for retrieving and updating timeseries data"""

    queryset = TimeSeries.objects.filter(active=True).prefetch_related(
        "dataset",
        "dataset__server",
        "data_type",
        "buffer_type",
        "platform",
    )
    # serializer_class = TimeSeriesSerializer
    # permission_classes = []

    # def get_queryset(self):
    #     return TimeSeries.objects.filter(active=True).prefetch_related(
    #         "dataset",
    #         "dataset__server",
    #         "data_type",
    #         "buffer_type",
    #         "platform"
    #     )

    def get_serializer_class(self):
        if self.request.method in {"POST", "PUT"}:
            return TimeSeriesUpdateSerializer
        return TimeSeriesSerializer

    # @action()
    # def batch(self, request):
    #     """List all the outdated timeseries"""
    #     pass

    # @action(detail=False, methods=["put"])
    # @authentication_classes([SessionAuthentication, TokenAuthentication])
    # @permission_classes([IsAuthenticated])
    # def batch(self, request):
    #     """Update a collection of timeseries.

    #     Timeseries will be matched by dataset slug, variable, and constraints,
    #     and the value and value times will be updated
    #     """
    #     serializer = TimeSeriesUpdateSerializer(data=request.data, many=True)

    #     updated_timeseries = []

    #     if serializer.is_valid():
    #         for updated_value in serializer.validated_data:
    #             print(updated_value)
    #             qs = TimeSeries.objects.by_dataset_slug(
    #                 updated_value["dataset"],
    #             ).filter(
    #                 variable=updated_value["variable"],
    #                 constraints=updated_value["constraints"],
    #             )
    #             update_count = qs.update(
    #                 value=updated_value["value"], value_time=updated_value["value_time"],
    #             )
    #             print(update_count)

    #             updated_timeseries.extend(qs.all())

    #             if update_count < 1:
    #                 print("Unable to update timeseries")

    #     serializer = TimeSeriesSerializer(
    #         updated_timeseries, many=True, context={"request": self.request},
    #     )
    #     # serializer = TimeSeriesUpdateResponseSerializer(
    #     #  {"updated_timeseries": updated_timeseries}, context={"request": self.request})
    #     return Response(serializer.data)


# [{"variable": "bar", "constraints": {"station=": "NAXR1"},
# "dataset": "Coastwatch-cwwcNDBCMet", "value": 42, "value_time": "2024-01-01T00:00:00"}]


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
