import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "buoy_barn.settings")

app = Celery("buoy_barn")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

# Imported for its side effect of connecting the metric signal receivers. It happens
# here rather than in the worker, because `before_task_publish` fires in whichever process
# publishes a task (web, beat, or the MQTT command) and `buoy_barn/__init__.py` imports
# this module, so every one of them ends up with the receivers installed.
from .observability import celery_signals  # noqa: E402,F401
