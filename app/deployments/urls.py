from rest_framework import routers

from .views import PlatformViewset


router = routers.DefaultRouter()
router.register('platforms', PlatformViewset)

urlpatterns = router.urls
