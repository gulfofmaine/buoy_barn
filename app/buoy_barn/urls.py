"""buoy_barn URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/2.0/topics/http/urls/

Examples
--------
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))

"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from health_check.views import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("deployments.urls")),
    path("api-auth/", include("rest_framework.urls")),
    path(
        "ht/",
        HealthCheckView.as_view(
            checks=[
                "health_check.Cache",
                "health_check.Database",
                # "health_check.Mail",
                "health_check.Storage",
                # 3rd party checks
                # "health_check.contrib.psutil.Disk",
                # "health_check.contrib.psutil.Memory",
                # "health_check.contrib.celery.Ping",
                # "health_check.contrib.rabbitmq.RabbitMQ",
                # "health_check.contrib.redis.Redis",
            ],
        ),
    ),
]


if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
