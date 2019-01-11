from rest_framework import serializers
from rest_framework.reverse import reverse


class ForecastSerializer(serializers.BaseSerializer):
    def to_representation(self, obj):

        return {
            "slug": obj.slug,
            "forecast_type": obj.forecast_type.value,
            "name": obj.name,
            "description": obj.description,
            "source_url": obj.source_url,
            "point_forecast": reverse("forecast-detail", kwargs={"pk": obj.slug}),
        }
