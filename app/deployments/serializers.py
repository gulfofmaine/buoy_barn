from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer, GeometrySerializerMethodField

from .models import Platform


# class PlatformSerializer(serializers.ModelSerializer):
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

    class Meta:
        model = Platform
        exclude = []
        id_field = "name"
        geo_field = 'location_point'