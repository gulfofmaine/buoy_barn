"""Generate forecast timeseries from EDR API references in STAC catalongs"""

import os
from datetime import datetime

import pandas as pd
import requests
from memoize import memoize
from pystac import Collection, Item, Link

from forecasts.forecasts.base_forecast import BaseForecast

RETRIEVE_FORECAST_CACHE_SECONDS = float(
    os.environ.get("RETRIEVE_FORECAST_CACHE_SECONDS", 15 * 60),
)
RETRIEVE_FORECAST_TIMEOUT_SECONDS = float(
    os.environ.get("RETRIEVE_FORECAST_TIMEOUT_SECONDS", 60),
)


class BaseSTACEDRForecast(BaseForecast):
    """Retrieve forecast from EDR endpoints accessible from STAC catalogs"""

    source_collection_url: str = NotImplemented
    field: str = NotImplemented
    edr_asset_key: str = "edr_api"
    date_pattern: str = NotImplemented

    @memoize(timeout=RETRIEVE_FORECAST_CACHE_SECONDS)
    def collection(self) -> Collection:
        """Returns the PySTAC Collection for the forecast"""
        return Collection.from_file(self.source_collection_url)

    @memoize(timeout=RETRIEVE_FORECAST_CACHE_SECONDS)
    def latest_item(self) -> Item:
        """Return the latest item in the collection"""
        link = latest_item_link_in_collection(self.collection(), self.date_pattern)
        return link.resolve_stac_object().target

    @memoize(timeout=RETRIEVE_FORECAST_CACHE_SECONDS)
    def point_forecast(self, lat: float, lon: float) -> list[tuple[datetime, float]]:
        """Return a forecast based using the latest forecast EDR response"""
        latest_item = self.latest_item()
        base_edr_url = latest_item.assets[self.edr_asset_key].href
        edr_url = edr_url_for_field(base_edr_url, self.field, lat, lon)
        response = requests.get(edr_url, timeout=RETRIEVE_FORECAST_TIMEOUT_SECONDS)
        forecast = forecast_from_response(response.json(), self.field)
        return forecast


def forecast_from_response(response_json, field: str) -> list[tuple[datetime, float]]:
    return list(
        zip(
            pd.to_datetime(
                response_json["domain"]["axes"]["t"]["values"],
            ).to_pydatetime(),
            response_json["ranges"][field]["values"],
            strict=False,
        ),
    )


def edr_url_for_field(
    base_url: str,
    field: str,
    latitude: float,
    longitude: float,
) -> str:
    wkt = f"POINT ({longitude} {latitude})"
    return base_url + f"?parameter-name={field}&coords={wkt}"


def latest_item_link_in_collection(collection: Collection, pattern: str) -> Link:
    """Find the latest item in the collection"""
    latest = None

    for link in collection.links:
        if link.rel == "item":
            item_date = datetime.strptime(
                link.href.split("/")[-1].removesuffix(".json"),
                pattern,
            )
            try:
                if item_date > datetime.strptime(
                    latest.href.split("/")[-1].removesuffix(".json"),
                    pattern,
                ):
                    latest = link
            except AttributeError:
                latest = link

    if latest is None:
        raise KeyError("No items in links")

    return latest
