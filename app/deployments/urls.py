from django.urls import path

from .views import PlatformList, PlatformDetail

urlpatterns = [
    path('platforms', PlatformList.as_view()),
    path('platforms/<str:pk>', PlatformDetail.as_view())
]