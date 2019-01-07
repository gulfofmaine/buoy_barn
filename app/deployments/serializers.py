from rest_framework import serializers
from rest_framework_gis.serializers import (
    GeoFeatureModelSerializer,
    GeometrySerializerMethodField,
)

from .models import Platform, Forecast


class PlatformSerializer(GeoFeatureModelSerializer):

    readings = serializers.SerializerMethodField()

    def get_readings(self, obj):
        return obj.latest_erddap_values()

    location_point = GeometrySerializerMethodField()

    def get_location_point(self, obj):
        try:
            return obj.location
        except AttributeError:
            return None

    attribution = serializers.SerializerMethodField()

    def get_attribution(self, obj):
        return [
            attr.json
            for attr in obj.programattribution_set.all().select_related("program")
        ]

    alerts = serializers.SerializerMethodField()

    def get_alerts(self, obj):
        return [alert.json for alert in obj.current_alerts()]

    class Meta:
        model = Platform
        exclude = ["geom"]
        id_field = "name"
        geo_field = "location_point"


class ForecastSerializer(serializers.ModelSerializer):

    server = serializers.SerializerMethodField()

    def get_server(self, obj):  # pylint: disable=R0201
        return obj.erddap_server.base_url

    latest_coverage_time = serializers.SerializerMethodField()

    def get_latest_coverage_time(self, obj):  # pylint: disable=R0201
        return obj.latest_coverage_time()

    class Meta:
        model = Forecast
        exclude = ["id", "erddap_server"]
