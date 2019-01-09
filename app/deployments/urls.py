from rest_framework import routers

from .views import PlatformViewset
from forecasts.views import ForecastViewSet


router = routers.DefaultRouter()
router.register("platforms", PlatformViewset)
router.register("forecasts", ForecastViewSet, base_name="forecast")

urlpatterns = router.urls
