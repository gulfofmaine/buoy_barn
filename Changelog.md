# CHANGELOG

## Upcoming (unknown release)

Additions:

Changes:

- Enable [Sentry Performance Monitoring](https://docs.sentry.io/product/performance/) for a subset of transactions.
- Enhance Sentry Releases using Github Action.

Fixes:

- Reduce need to access secrets during testing to reduce problems with PRs from forks. See [1](https://github.community/t/dependabot-prs-and-workflow-secrets/163269/23) [2](https://github.community/t/dependabot-doesnt-see-github-actions-secrets/167104/25)
- Fix ordering of quotes in ERDDAP dataset test links so that they don't cancel out station ids or other string quoted constraints.
- Handle more types of ERDDAP errors when fetching data, and hopefully report them more usefully to Sentry.

## 0.3.4 - 03/17/2021

Fixes:

- Flow scheduling check almost always would not schedule flows.

## 0.3.3 - 03/17/2021

Changes:

- Add ability to test timeseries setup on the admin.
- Add default hourly dataset refresh.
- Speed up platform admin.

Fixes:

- Only schedule flows in production.

## 0.3.2 - 03/15/2021

Changes:

- Add active toggle for timeseries that determines if they should be updated.


## 0.3.1 - 03/08/2021

Changes:

- Simplified Kubernetes configuration and made it compatible with Argo CD. [#317](https://github.com/gulfofmaine/buoy_barn/pull/317)
- Updated Dockerfile to use buildkit caching. [#317](https://github.com/gulfofmaine/buoy_barn/pull/317)
- Updated Github Actions workflow to push images to Docker Hub and configs to Argo CD repo. [#317](https://github.com/gulfofmaine/buoy_barn/pull/317)
- Update Dependencies:
  - Poetry from 1.0.3 too 1.1.5
  - Prefect from 0.14.10 to 0.14.11
  - IPython from 7.20 to 7.21

## 0.3.0 - 02/24/2021

Additions:

- Multiple forecasts! First addition of a new forecast with NECOFS

## 0.2.1 - 02/24/2021

Fixes:

- Shift daily cron Prefect tick later

## 0.2.0 - 02/23/2021

Additions:

- Use Prefect to check for outdated time series.

Changes:

- Update dependencies:
  - Actions/checkout from v1 to v2.3.4
  - Python from 3.9.1 to 3.9.2
  - NetCDF4 from 1.5.5 to 1.5.6
  - Sentry SDK from 0.19.5 to 0.20.3
  - Pandas to 1.2.2 (from <2.0.0)
- Use Dependabot to update Github Actions

Fixes:

- Use Buildx for Github Actions.
- Increase timeout on Github Actions build.

## 0.1.18 - 02/12/2021

Fixes:

- Sort dataframes from ERDDAP by time before use. IOOS Sensor ERDDAP has a tendency to return data from latest to earliest, rather than from earliest to latest like all other ERDDAPs that I've tested against. [#287](https://github.com/gulfofmaine/buoy_barn/issues/287)

## 0.1.17 - 02/09/2021

Fixes:

- Not everything forecast was returning a date in it's time series.

## 0.1.16 - 02/09/2021

Changes:

- Update dependencies:
  - Python from 3.8.6 to 3.9.1
  - Celery from 4.4 to 5.0
  - Django CORS Headers from 3.6 to 3.7
  - Django Rest Framework GIS from 0.16 to 0.17
  - Freezegun from 1.0.0 to 1.1.0
  - IPython from 7.19 to 7.20
  - PyYaml from 5.3.1 tp 5.4
  - Py.test coverage from 2.10 to 2.11

Fixes:

- Include `Z` on the end of forecast dates to specify the timezone so that browsers don't guess.

## 0.1.15 - 12/15/2020

Changes:

- Added admin command to clear end times set on TimeSeries by Platform. This makes it easier to clear out automatically set end times.
- Update dependencies:
  - Django CORS Headers from 3.1 to 3.5
  - Django Debug Toolbar from 3.1 to 3.2
  - ERDDAPY from 0.7.2 to 0.9.0
  - NetCDF 4 from 1.5.4 to 1.5.5
  - Sentry SDK from 0.19.2 to 0.19.5
  - xarray from 0.16.1 to 0.16.2

## 0.1.14 - 11/3/2020

Fixes:

- Add test and comparison for invalid constraints.

## 0.1.13 - 11/3/2020

Fixes:

- Add test and tweak comparison for actual range error.

## 0.1.12 - 11/3/2020

Changes:

- Use `-slim` Docker image as a base to make for a lighter image (1.44 too .91 GB).
- Update dependencies
  - Sentry SDK from 0.18.0 to 0.19.2
  - IPython from 7.18 to 7.19
  - Pytest Django from 3.10 to 4.1
  - Django from 3.1.2 to 3.1.3

Fixes:

- Handle date parsing errors and when a constraint is outside of the actual range.

## 0.1.11 - 10/5/2020

Changes:

- Include release version with Sentry init
- Add CodeQL analysis
- Use Pandas and CSV rather than NetCDF > Pandas and NetCDF to retrieve data from ERDDAP servers.
- Update dependencies
  - Erddapy from 0.5.3 to 0.7.2
  - Pandas from 0.25.3 to 1.1.3

Fixes:

- Catch and handle various 500 errors during time series update task smarter.
  - If `nRows = 0` quietly pass.
  - If the dataset has an end time set, set an end time on the time series to stop fetching it.
  - Return early from errors to make it easier to read.

## 0.1.10 - 9/30/2020

Changes:

- Add oxygen_concentration_in_sea_water data type.
- Bedford wave forecast should be significant wave height.
- Update dependencies
  - Python from 3.8.5 to 3.8.6
  - Django Debug Toolbar from 2.2 to 3.1
  - Django Rest Framework from 3.11 to 3.12
  - Sentry SDK from 0.17.7 to 0.18.0
  - py.test from 6.0 to 6.1

Fixes:

- Prevent debug toolbar from being loaded during tests.

## 0.1.9 - 9/23/2020

Changes:

- Add caching to the platforms API view.
- Update TimeSeries.constraints to use Django JSONField rather than Postgres.
- Order DataTypes
- Remove unused Deployment model.
- Update Dependencies
  - Python from 3.8.2 to 3.8.5
  - Django from 3.0 to 3.1
  - Django CORS Headers from 3.2 to 3.5
  - Django Redis from 4.11 to 4.12
  - Django Rest Framework GIS from 0.15 to 0.16
  - FreezeGun from 0.3.15 to 1.0.0
  - NetCDF4 from 1.5.3 to 1.5.4
  - Psycopg2 Binary from 2.8.5 to 2.8.6
  - Sentry SDK from 0.14.3 to 0.17.7
  - UWSGI from 2.0.18 to 2.0.19
  - VCRpy from 4.0 to 4.1
  - Whitenoise from 5.0 to 5.2
  - Xarray from 0.15.1 to 0.16.1
  - IPython from 7.13 to 7.18
  - py.test from 5.4 to 6.0
  - py.test Django from 3.9 to 3.10
  - py.test cov from 2.8 to 2.10
  - Prospector from 1.2 to 1.3

Fixes:

- `.prefetch_related()` for platforms API view to reduce the number of queries by 100 fold, and equally speeding up access.
- Better error handling of ERDDAP response status codes when there is an error.

Testing:

- Test HTTP 500 errors in tasks.

## 0.1.8 - 4/30/2020

Fixes:

- Quiet 500 errors also as infos.

## 0.1.7 - 4/30/2020

Fixes:

- Decreased `OSError` in refresh task to `logger.info` as it appears to largely be caused when the UConn ERDDAP is returning 0 rows and we try to read a webpage as a NetCDF.

## 0.1.6 - 4/30/2020

Fixes:

- 403 Blacklist error was being caught as a warning.
- Update dependencies
  - Django Memoize from 2.2.1 to 2.3.1

## 0.1.5 - 4/7/2020

Changes:

- Add Redis integration to Sentry.
- Update Kubernetes configs from various beta versions to apps/v1.

## 0.1.4 - 4/7/2020

Changes:

- Update Bedford wave height period (previously the Wave Watch 3 model was using the wrong wave period from the model).
- Update dependencies
  - Python from 3.8.1 to 3.8.2
  - Freezegun from 0.3.12
  - Celery from 4.4.0 to 4.4.2
  - Django from 3.0.3 to 3.0.5
  - IPython from 7.12.0 to 7.13.0
  - Pandas from 1.0.1 to 1.0.3
  - Psycopg2-binary from 2.8.4 to 2.8.5
  - Pytest from 5.3.5 to 5.4.1
  - Pytest django from 3.8.0 to 3.9.0
  - PyYAML from 5.3 to 5.3.1
  - Sentry SDK from 0.14.1 to 0.14.3
  - Xarray from 0.15.0 to 0.15.1

Fixes:

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
