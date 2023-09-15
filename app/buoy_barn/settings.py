"""
Django settings for buoy_barn project.

Generated by 'django-admin startproject' using Django 2.0.9.

For more information on this file, see
https://docs.djangoproject.com/en/2.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.0/ref/settings/
"""

import logging
import os

import sentry_sdk
import toml
from corsheaders.defaults import default_headers
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration

logger = logging.getLogger(__name__)

# SECURITY WARNING: don't run with debug turned on in production!

DEBUG = os.environ.get("DJANGO_ENV", "").lower() == "dev"


def before_send(event, hint):
    """Don't report "OSError: write error" to Sentry.

    via: https://stumbles.id.au/how-to-fix-uwsgi-oserror-write-error.html
    """
    exc_type, exc_value, _ = hint.get("exc_info", [None, None, None])
    if exc_type == OSError and str(exc_value) == "write error":
        return None
    return event


SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", 0))
SENTRY_IGNORE_PATHS = {"/ht/"}


def trace_filter(trace: dict) -> float:
    """Filter out unwanted sentry transactions"""

    try:
        path: str = trace["wsgi_environ"]["PATH_INFO"]

        if path in SENTRY_IGNORE_PATHS:
            return 0  # don't trace

        if path.startswith("/static/"):
            return 0

    except KeyError:
        pass

    return SENTRY_TRACES_SAMPLE_RATE


if os.environ.get("DJANGO_ENV", "").lower() != "test":
    try:
        pyproject = toml.load("pyproject.toml")
        version = pyproject["tool"]["poetry"]["version"]
        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            integrations=[CeleryIntegration(), DjangoIntegration(), RedisIntegration()],
            environment="dev" if DEBUG else "prod",
            release=f"v{version}",
            traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
            traces_sampler=trace_filter,
            before_send=before_send,
        )
        logger.info("Sentry initialized")
    except KeyError:
        logger.warning("SENTRY_DSN missing. Sentry is not initialized")
else:
    logger.info("Sentry disabled when DJANGO_ENV=test")

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(__file__))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ["SECRET_KEY"]


ALLOWED_HOSTS = ["*"]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "rest_framework_gis",
    "corsheaders",
    "memoize",
    # Health checks to allow Kubernetes to restart the pod if locked up
    "health_check",
    "health_check.db",
    "health_check.cache",
    # "health_check.contrib.celery_ping",
    # User management
    "account.apps.AccountConfig",
    # Dataset and forecast management
    "deployments.apps.DeploymentsConfig",
    "forecasts.apps.ForecastsConfig",
]

AUTH_USER_MODEL = "account.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_HEADERS = (
    *default_headers,
    "baggage",
    "sentry-trace",
)

ROOT_URLCONF = "buoy_barn.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_CACHE", "redis://cache:6379/0"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    },
}

# How many seconds should CORS proxied data from ERDDAP servers be cached
PROXY_CACHE_SECONDS = int(os.environ.get("PROXY_CACHE_SECONDS", 60))

# How many seconds should requests wait before timing out connecting to a proxy
PROXY_TIMEOUT_SECONDS = int(os.environ.get("PROXY_TIMEOUT_SECONDS", 30))

# How many seconds should requests wait before timing out connecting to an ERDDAP server
# When it isn't already defined by a model
ERDDAP_TIMEOUT_SECONDS = int(os.environ.get("ERDDAP_TIMEOUT_SECONDS", 30))

WSGI_APPLICATION = "buoy_barn.wsgi.application"


# Database
# https://docs.djangoproject.com/en/2.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("POSTGRES_NAME"),
        "USER": os.environ.get("POSTGRES_USER"),
        "HOST": os.environ.get("POSTGRES_HOST"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
        "PORT": int(os.environ.get("POSTGRES_PORT", 5432)),
        "OPTIONS": {"sslmode": "prefer"},
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"


# Password validation
# https://docs.djangoproject.com/en/2.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
# https://docs.djangoproject.com/en/2.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True


USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

STATIC_URL = "/static/"

STATIC_ROOT = "/static/"

# Celery TASK management
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL")

if DEBUG:
    INSTALLED_APPS = INSTALLED_APPS + ["debug_toolbar"]
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE

    def show_toolbar(request):
        return True

    DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": show_toolbar}
