import logging

from django.urls import reverse
from rest_framework import serializers
from rest_framework_gis.serializers import (
    GeoFeatureModelSerializer,
    GeometrySerializerMethodField,
)

from .models import ErddapDataset, ErddapServer, Platform, Program, TimeSeries

logger = logging.getLogger(__name__)


class PlatformSerializer(GeoFeatureModelSerializer):
    readings = serializers.SerializerMethodField()

    def get_readings(self, obj):
        readings = []

        try:
            timeseries: list[TimeSeries] = obj.timeseries_active
        except AttributeError:
            timeseries: list[TimeSeries] = obj.timeseries_set.filter(active=True)

        for series in timeseries:
            if not series.end_time:
                datums = {}
                for datum_name in TimeSeries.DATUMS:
                    value = getattr(series, datum_name, None)
                    if value is not None:
                        datums[datum_name] = value

                readings.append(
                    {
                        "value": series.value,
                        "time": series.value_time,
                        "depth": series.depth,
                        "data_type": series.data_type.json,
                        "server": series.dataset.server.base_url,
                        "variable": series.variable,
                        "constraints": series.constraints,
                        "dataset": series.dataset.name,
                        "start_time": series.start_time,
                        "cors_proxy_url": reverse(
                            "server-proxy",
                            kwargs={"server_id": series.dataset.server.id},
                        )
                        if series.dataset.server.proxy_cors
                        else None,
                        "datum_offsets": datums,
                    },
                )

        return readings

    location_point = GeometrySerializerMethodField()

    def get_location_point(self, obj):
        try:
            return obj.location
        except AttributeError:
            logger.error(
                f"Platform ({obj.name}) does not have a valid location attribute",
                exc_info=True,
            )
            return None

    attribution = serializers.SerializerMethodField()

    def get_attribution(self, obj):
        return [attr.json for attr in obj.programattribution_set.all()]

    alerts = serializers.SerializerMethodField()

    def get_alerts(self, obj):
        return [alert.json for alert in obj.current_alerts()]

    class Meta:
        model = Platform
        exclude = ["geom"]
        id_field = "name"
        geo_field = "location_point"


class ProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = ("name", "website")


class ErddapServerSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = ErddapServer
        fields = ("name", "base_url", "url")
        depth = 1


class ErddapDatasetSerializer(serializers.ModelSerializer):
    slug = serializers.ReadOnlyField()
    server = ErddapServerSerializer()

    class Meta:
        model = ErddapDataset
        fields = ("name", "server", "slug")
        depth = 2

    def get_slug(self, obj):
        return f"{obj.server.name}-{obj.name}"
