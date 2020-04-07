# CHANGELOG

## Upcoming (unknown release)

Additions:

Changes:

- Update Bedford wave height period (previously the Wave Watch 3 model was using the wrong wave period from the model).

Fixes

- Adds timeout when a task does not return a response.
- Catches when a 500 page is returned instead of an NetCDF file.
- Catch JSON decode errors when trying to load forecasts.

## 0.1.3 - 2/12/20

Changes:

- Test using Github Actions.
- Replace Pip-tools with Poetry for dependency management.
- Use py.test to manage testing
- Update dependencies
  - Django from 2.2.5 to 3.0
  - Psycopg2-binary from 2.8.3 to 2.8.4
  - Django CORS headers from 3.1.0 to 3.2
  - Django Rest Framework from 3.10.3 to 3.11
  - Django Rest Framework GIS from 0.14 to 0.15
  - Django Memoize from 2.2.0 to 2.2.1
  - Django Redis from 4.10 to 4.11
  - Erddapy from 0.5.0 to 0.5.3
  - Xarray from 0.12.3 to 0.15.0
  - netCDF4 from 1.5.2 to 1.5.3
  - Sentry SDK from 0.11.2 to 0.14.1
  - Celery from 4.3.0 to 4.4
  - Whitenoise from 4.1.3 to 5.0
  - IPython from 7.8.0 to 7.12
  - Django Debug Toolbar from 2.0 to 2.2
  - Prospector from 1.1.7 to 1.2
  - VCR from 2.1 to 4

Fixes:

- Issue where constraints are not set blocks whole server from updating

## 0.1.2 - 9/4/19

Fixes:

- Issue when values returned from ERDDAP as Timedelta rather than a float.

## 0.1.1 - 9/4/19

Changes:

- Set live version sending to Sentry
- Update dependencies
  - Binutils from 2.28-5 to 2.31.1-16
  - Libproj-dev from 4.9.3-1 to 5.2.0-1
  - Gdal-bin from 2.1.2+dfsg-5 to 2.4.0+dfsg-1+b1
  - Django from 2.2.2 to 2.2.5
  - Django Rest Framework from 3.9.4 to 3.10.0
  - Erddapy from 0.4.0 to 0.5.0
  - netCDF4 from 1.5.1.2 to 1.5.2
  - iPython from 7.7.0 to 7.8.0
  - Sentry-sdk from 0.9.2 to 0.11.2
  - Django CORS headers from 2.5.2 to 3.1.0
  - Django debug toolbar from 1.11 to 2.0
  - Prospector from 1.1.6.2 to 1.1.7
  - Coverage from 4.5.3 to 4.5.4
  - PyYAML from 5.1 to 5.1.2
  - Geojson from 2.4.1 to 2.5.0
  - VCRpy from 2.0.1 to 2.1.0
  - Freezegun from 0.3.11 to 0.3.12
  - Pip-tools from 3.8.0 to 4.1.0

Fixes:

- `self.assertEquals` has been depricated, so using `self.asertEqual`

## 7/19/19

Additions:

- Migrate deployment to Kubernetes using Kustomize and Skaffold.
