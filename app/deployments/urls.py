from rest_framework import routers

from .views import PlatformViewset, DatasetViewSet, ServerViewSet
from forecasts.views import ForecastViewSet


router = routers.DefaultRouter()
router.register("platforms", PlatformViewset)
router.register("datasets", DatasetViewSet)
router.register("servers", ServerViewSet)
router.register("forecasts", ForecastViewSet, base_name="forecast")

urlpatterns = router.urls
