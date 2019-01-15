from collections import Counter
from urllib.parse import quote

from django.apps import AppConfig
from django.core.checks import Error, register

from forecasts.forecasts import forecast_list
from forecasts.forecasts.base_forecast import BaseForecast, ForecastTypes
from forecasts.forecasts.base_erddap_forecast import BaseERDDAPForecast


class ForecastsConfig(AppConfig):
    name = "forecasts"


@register()
def check_duplicate_forecasts(app_configs, **kwargs):  # pylint: disable=unused-argument
    """ Return errors for any forecasts with duplicate slugs """
    errors = []

    slug_counter = Counter([forecast.slug for forecast in forecast_list])

    for slug, count in slug_counter.items():
        forecasts_for_slug = ", ".join(
            [
                str(forecast.__class__)
                for forecast in forecast_list
                if forecast.slug == slug
            ]
        )

        if count > 1:
            errors.append(
                Error(
                    "Duplicate Forecast Slug",
                    hint=f"{forecasts_for_slug} have a shared slug ({slug}). Forecasts with duplicate slugs cannot be accessed.",
                    id="forecasts.E001",
                )
            )

        if slug != quote(slug):
            errors.append(
                Error(
                    "Invalid slug format",
                    hint=f"{forecasts_for_slug} have a slug ({slug}) with invalid characters that cannot be part of a URL",
                    id="forecasts.E002",
                )
            )

    return errors


@register()
def check_forecasts(app_configs, **kwargs):  # pylint: disable=unused-argument
    """ Check forecast attributes and methods are implemented """
    errors = []

    for forecast in forecast_list:
        forecast_str = str(forecast.__class__)

        if forecast.slug == NotImplemented:
            errors.append(
                Error(
                    "slug is not implemented",
                    hint=f"{forecast_str} has not implemented a slug attribute",
                    id="forecasts.E011",
                )
            )

        if forecast.forecast_type == NotImplemented:
            errors.append(
                Error(
                    "forecast_type is not implemented",
                    hint=f"{forecast_str} has not implemented a forecast_type attribute",
                    id="forecasts.E012",
                )
            )

        if not isinstance(forecast.forecast_type, ForecastTypes):
            errors.append(
                Error(
                    "forecast_type is not a ForecastType",
                    hint=f"{forecast_str} has a forecast_type that is not a ForecastType enum.",
                    id="forecasts.E013",
                )
            )

        if forecast.name == NotImplemented:
            errors.append(
                Error(
                    "name is not implemented",
                    hint=f"{forecast_str} has not implemented name attribute",
                    id="forecasts.E014",
                )
            )

        if forecast.description == NotImplemented:
            errors.append(
                Error(
                    "description is not implemented",
                    hint=f"{forecast_str} has not implemented a description attribute",
                    id="forecasts.E015",
                )
            )

        if forecast.source_url == NotImplemented:
            errors.append(
                Error(
                    "source_url is not implemented",
                    hint=f"{forecast_str} has not implemented a source_url attributel",
                    id="forecasts.E016",
                )
            )

        if forecast.units == NotImplemented:
            errors.append(
                Error(
                    "units is not implemented",
                    hint=f"{forecast_str} has not implemented a units attribute",
                    id="forecasts.E017",
                )
            )

        # Check that the point_forecast methods are not the same https://stackoverflow.com/a/20059029
        if (
            forecast.point_forecast.__code__.co_code
            == BaseForecast.point_forecast.__code__.co_code
        ):
            errors.append(
                Error(
                    "point_forecast has not been implemented",
                    hint=f"{forecast_str} has not implemented a point_forecast method",
                    id="forecasts.E021",
                )
            )

        # additional checks for ERDDAP forecasts
        if isinstance(forecast, BaseERDDAPForecast):
            if forecast.server == NotImplemented:
                errors.append(
                    Error(
                        "server is not implemented",
                        hint=f"{forecast_str} has not implemented a server attribute",
                        id="forecasts.E031",
                    )
                )

            if forecast.dataset == NotImplemented:
                errors.append(
                    Error(
                        "dataset is not implenented",
                        hint=f"{forecast_str} has not implemeted a dataset attribute",
                        id="forecasts.E032",
                    )
                )

            if (
                forecast.field == NotImplemented
                and forecast.point_forecast.__code__.co_code
                == BaseERDDAPForecast.point_forecast.__code__.co_code
            ):
                errors.append(
                    Error(
                        "field is not implemented",
                        hint=f"{forecast_str} has not implemented a field attribute, and the point_forecast method has not been overridden",
                        id="forecasts.E033",
                    )
                )

    return errors
