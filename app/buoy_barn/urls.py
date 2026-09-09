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

from datetime import timedelta

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from health_check.views import HealthCheckView

urlpatterns = [
    # Control room URLs go before admin URLs
    path("admin/dj-cache-panel/", include("dj_cache_panel.urls")),
    path("admin/dj-signals-panel/", include("dj_signals_panel.urls")),
    path("admin/dj-urls-panel/", include("dj_urls_panel.urls")),
    path("admin/dj-redis-panel/", include("dj_redis_panel.urls")),
    path("admin/dj-celery-panel/", include("dj_celery_panel.urls")),
    path("admin/dj-control-room/", include("dj_control_room.urls")),
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
                #   Left off on purpose. This view backs the Kubernetes *liveness* probe,
                #   and Ping raises if any queue has no worker replying within 1 second --
                #   so a merely busy worker would restart the web pods. Worker health is
                #   covered instead by buoybarn.celery.task.* and
                #   buoybarn.celery.queue.depth (see docs/observability.md). A Celery ping
                #   is available at /ht/celery/ below for manual/dashboard use, but per its
                #   own comment it must never back a probe that restarts anything.
                # "health_check.contrib.rabbitmq.RabbitMQ",
                # "health_check.contrib.redis.Redis",
            ],
        ),
    ),
    path(
        "ht/celery/",
        # A separate endpoint, not a check added to /ht/ above. The tuple form (dotted
        # path + options dict) is used instead of importing Ping directly, because that's
        # what HealthCheckView.get_checks expects: it calls check(**options) on each pair.
        # 10s instead of Ping's 1s default because a busy worker is not a dead one.
        #
        # WARNING: Ping.check_active_queues makes a *second* round trip via
        # self.app.control.inspect(...), and that inspect call does not take our timeout --
        # it always uses Celery's own hardcoded 1.0s default. Because of that, this endpoint
        # must never be wired to a probe that restarts anything (it must never become the
        # Kubernetes web liveness probe, for instance) -- a merely-busy worker could still
        # fail the inspect leg and take down whatever this is attached to.
        HealthCheckView.as_view(
            checks=[
                ("health_check.contrib.celery.Ping", {"timeout": timedelta(seconds=10)}),
            ],
        ),
    ),
]


if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
