from django.urls import re_path
from rest_framework import routers

from .views import PlatformViewset, DatasetViewSet, ServerViewSet, server_proxy
from forecasts.views import ForecastViewSet


router = routers.DefaultRouter()
router.register("platforms", PlatformViewset)
router.register("datasets", DatasetViewSet)
router.register("servers", ServerViewSet)
router.register("forecasts", ForecastViewSet, basename="forecast")

urlpatterns = [
    re_path(r"servers/(?P<server_id>[0-9])/proxy/", server_proxy, name="server-proxy")
] + router.urls
