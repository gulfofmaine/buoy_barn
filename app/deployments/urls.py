from django.urls import re_path
from rest_framework import routers

from forecasts.views import ForecastViewSet

from .views import DatasetViewSet, PlatformViewset, ServerViewSet, server_proxy

router = routers.DefaultRouter()
router.register("platforms", PlatformViewset)
router.register("datasets", DatasetViewSet)
router.register("servers", ServerViewSet)
router.register("forecasts", ForecastViewSet, basename="forecast")

urlpatterns = [
    re_path(
        r"servers/(?P<server_id>\d{1,10})/proxy/",
        server_proxy,
        name="server-proxy",
    ),
] + router.urls
