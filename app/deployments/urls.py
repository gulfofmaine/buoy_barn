from rest_framework import routers

from .views import PlatformViewset, ForecastViewset


router = routers.DefaultRouter()
router.register("platforms", PlatformViewset)
router.register("forecasts", ForecastViewset)

urlpatterns = router.urls
