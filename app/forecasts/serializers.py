from rest_framework import serializers


class ForecastSerializer(serializers.BaseSerializer):
    def to_representation(self, obj):
        return {
            "slug": obj.slug,
            "forecast_type": obj.forecast_type.value,
            "name": obj.name,
            "description": obj.description,
            "source_url": obj.source_url,
        }
