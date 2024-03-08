"""Forecast JSON serializer"""

from rest_framework import serializers
from rest_framework.reverse import reverse


class ForecastSerializer(serializers.BaseSerializer):
    """Serialize forecast information to JSON"""

    def to_representation(self, instance):  # pylint: disable=no-self-use
        """Convert forecast instance to JSON"""
        return {
            "slug": instance.slug,
            "forecast_type": instance.forecast_type.value,
            "name": instance.name,
            "description": instance.description,
            "source_url": instance.source_url,
            "point_forecast": reverse("forecast-detail", kwargs={"pk": instance.slug}),
            "units": instance.units,
        }
