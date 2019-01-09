from forecasts.forecasts.base_erddap_forecast import BaseERDDAPForecast


class BaseNERACOOSERDDAPForecast(BaseERDDAPForecast):
    server = "http://www.neracoos.org/erddap"
