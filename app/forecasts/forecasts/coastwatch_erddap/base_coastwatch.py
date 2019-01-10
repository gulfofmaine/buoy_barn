from forecasts.forecasts.base_erddap_forecast import BaseERDDAPForecast


class BaseCoastWatchRDDAPForecast(BaseERDDAPForecast):
    server = "https://coastwatch.pfeg.noaa.gov/erddap"
