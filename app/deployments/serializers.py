from rest_framework import serializers
from rest_framework_gis.serializers import (
    GeoFeatureModelSerializer,
    GeometrySerializerMethodField,
)
from sentry_sdk import capture_message

from .models import Platform, ErddapDataset, ErddapServer, Program


class PlatformSerializer(GeoFeatureModelSerializer):

    readings = serializers.SerializerMethodField()

    def get_readings(self, obj):
        return obj.latest_erddap_values()

    location_point = GeometrySerializerMethodField()

    def get_location_point(self, obj):
        try:
            return obj.location
        except AttributeError:
            capture_message(
                f"Platform ({obj.name}) does not have a valid location attribute"
            )
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

    class Meta:
        model = ErddapDataset
        fields = ("name", "server", "slug")
        depth = 2

    def get_slug(self, obj):
        print(self, obj)
        return f"{obj.server.name}-{obj.name}"
