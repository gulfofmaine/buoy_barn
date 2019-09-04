"""
Django settings for buoy_barn project.

Generated by 'django-admin startproject' using Django 2.0.9.

For more information on this file, see
https://docs.djangoproject.com/en/2.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.0/ref/settings/
"""

import os
import logging

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

logger = logging.getLogger(__name__)

# SECURITY WARNING: don't run with debug turned on in production!
try:
    DEBUG = bool(os.environ["DJANGO_DEBUG"] != "False")
except KeyError:
    DEBUG = False

try:
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        integrations=[CeleryIntegration(), DjangoIntegration()],
        environment="dev" if DEBUG else "prod",
    )
    logger.info("Sentry initialized")
except KeyError:
    logger.warning("SENTRY_DSN missing. Sentry is not initalized")

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    "debug_toolbar",
    "rest_framework",
    "rest_framework_gis",
    "corsheaders",
    "memoize",
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

CORS_ORIGIN_ALLOW_ALL = True

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
            ]
        },
    }
]

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_CACHE", "redis://cache:6379/0"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

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
    }
}


# Password validation
# https://docs.djangoproject.com/en/2.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
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

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.0/howto/static-files/

STATIC_URL = "/static/"

STATIC_ROOT = "/static/"

# Celery TASK management
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL")
