# CHANGELOG

## Upcoming (unknown release)

Additions:

Changes:

Fixes:

## 0.6.8 - 10/28/2024

Changes:
- Switch to using Docker Compose watch mode
- Enabled GZip middleware
- Restructured the inline timeseries admins in platform admin panels to bring the common fields to the forefront, but have a collapsed inline for some advanced fields.

Dependency updates:
- Switched to using uv rather than Poetry
- Github Actions
  - Setup Docker Buildx from 3.3.0 to 3.7.1
  - Docker login from 3.1.0 to 3.3.0
  - Docker build push from 5.3.0 to 6.9.0
- Pre-commit
  - Pre-commit-hooks from 4.6.0 to 5.0.0
  - Bandit from 1.7.8 to 1.7.10
  - Gitleaks from 8.18.2 to 8.21.2
  - Shellcheck from 0.9.0.6 to 0.10.0.1
  - Django Upgrade from 1.16.0 to 1.22.0
  - Pyproject Format from 1.8.0 to 2.4.3
  - Ruff from 0.4.1 to 0.7.1
- Docker
  - Redis from 7.2.4 to 7.2.5


## 0.6.7 - 04/25/2024

Changes:

- Add the ability to highlight timeseries https://github.com/gulfofmaine/buoy_barn/pull/1099

Fixes:

- Ignore long migrations line errors in Ruff

Dependency updates:

- Pre-commit
  - Pyproject Format from 1.7.0 to 1.8.0
  - Ruff from 0.3.5 to 0.4.1
- Python
  - Celery from 5.3 to 5.4
  - Freezegun from 1.4.0 to 1.5.0
  - UWSGI from 2.0.24 to 2.0.25

## 0.6.6 - 04/15/2024

Fixes:

- Only Slack at the top of the hour about out of date timeseries, instead of every minute https://github.com/gulfofmaine/buoy_barn/pull/1088

## 0.6.5 - 04/11/2024

Changes:

- Add station name and rename station slug in https://github.com/gulfofmaine/buoy_barn/pull/1083
- Notify about out of date timeseries in https://github.com/gulfofmaine/buoy_barn/pull/1084

Dependency Updates:

- Github Actions
  - Setup Docker Buildx from 3.0.0 to 3.3.0
  - Docker Login from 3.0.0 to 3.1.0
  - Docker Build Push from 5.1.0 to 5.3.0
  - Pre-commit from 3.0.0 to 3.0.1
- Pre-commit
  - Pre-commit-hooks from 4.5.0 to 4.6.0
  - Bandit from 1.7.7 to 1.7.8
  - Gitleaks from 8.18.1 to 8.18.2
  - Django Upgrade from 1.15.0 to 1.16.0
  - Ruff from 0.1.15 to 0.3.5
- Docker
  - Syntax from 1.6 to 1.7
- Python
  - Django Debug Toolbar from 4.2 to 4.3
  - Django Rest Framework from 3.14 to 3.15
  - Sentry-SDK from 1.40.0 to 1.45.0
  - uWSGI from 2.0.23 to 2.0.24
  - Django Health Check from 2.18.0 to 3.18.1
  - PyStac from 1.9.0 to 1.10.0
  - IPython from 8.20 to 8.23
  - Py.test from 8.0 to 8.1
  - Py.test Cov from 4.1 to 5.0
  - Xarray from 2024.1.1 to 2024.3.0

## 0.6.4 - 01/30/2024

Changes

- Added refresh actions to platform, dataset, and server admin pages closing [#289](https://github.com/gulfofmaine/buoy_barn/issues/289). [#1020](https://github.com/gulfofmaine/buoy_barn/pull/1020)

## 0.6.3 - 01/30/2024

Changes:

- Switch formatting and linting to Ruff. [#990](https://github.com/gulfofmaine/buoy_barn/pull/990)
- Configure Sentry Spotlight for development. [#1016](https://github.com/gulfofmaine/buoy_barn/pull/1016)

Fixes:

- Recover from invalid data type errors. [#1016](https://github.com/gulfofmaine/buoy_barn/pull/1016)

Dependency Updates:

- Github Actions
  - Cache from v3 to v4
- Pre-commit
  - Bandit from 1.7.6 to 1.7.7
- Python
  - Sentry SDK from 1.39.2 to 1.40.0
  - Xarray from 2023.12.0 to 2024.1.1
  - Django Health Check from 3.17.0 to 3.18.0
  - Py.test from 7.4 to 8.0
  - Py.test Django from 4.7 to 4.8
- Docker
  - Redis from 7.2.3 to 7.2.4

## 0.6.2 - 01/12/2024

Fixes:

- Fix for when a celery worker queue is empty, part 2.

## 0.6.1 - 01/11/2024

Fixes:

- Fix for when a celery worker queue is empty. [#1000](https://github.com/gulfofmaine/buoy_barn/pull/1000)

## 0.6.0 - 01/11/2024

Additions:

- Tidal datums, platform type, and various tidal data types. [#903](https://github.com/gulfofmaine/buoy_barn/pull/903)
- The ability to define both standard (minor, moderate, and major) and custom flooding levels for individual time series. [#986](https://github.com/gulfofmaine/buoy_barn/pull/986)
- Platform specific links for more info. [#997](https://github.com/gulfofmaine/buoy_barn/pull/997)
- Initial work towards being able to push observations to Buoy Barn, rather than waiting for it to fetch. [#902](https://github.com/gulfofmaine/buoy_barn/pull/902)

Changes:

- Use OGC EDR API to fetch FVCOM and BIO forecasts to build on our work fetching that data for modeling, and reducing the real time dependency on UMass servers. [#985](https://github.com/gulfofmaine/buoy_barn/pull/985)
- Moved from Prefect to Celery beat for periodic tasks. [#989](https://github.com/gulfofmaine/buoy_barn/pull/989)
- Cleaned up the admin for time series configuration, and moved many of the advanced options to a separate configuration screen. [#986](https://github.com/gulfofmaine/buoy_barn/pull/986)

Fixes:

- Some Sentry headers sometimes caused CORS errors. [#903](https://github.com/gulfofmaine/buoy_barn/pull/903)

Dependency Updates:

- Github Actions
  - Checkout from 3 to 4
  - Setup Docker Buildx from 2.9.1 to 3.0.0
  - Docker Login from 2.2.0 to 3.0.0
  - Docker build push from 4.1.1 to 5.1.0
  - Sentry release from 1.4.1 to 1.7.0
  - CodeQL from 2 to 3
    - Init
    - Autobuild
    - Analyze
  - Setup Python from 4 to 5
- Pre Commit
  - Pre-commit-hooks from 4.4.0 to 4.5.0
  - Blackdoc from 0.3.8 to 0.3.9
  - Flake8 from 6.0.0 to 7.0.0
  - Isort from 5.12.0 to 5.13.0
  - Black from 23.7.0 to 23.12.1
  - PyUpgrade from 3.9.0 to 3.15.0
  - Add trailing comma from 3.0.0 to 3.1.0
  - Bandit from 1.7.5 to 1.7.6
  - Gitleaks from 8.17.0 to 8.18.1
  - Shellcheck from 0.9.0.5 to 0.9.0.6
  - Django Upgrade from 1.14.0 to 1.15.0
- Python
  - Python itself from 3.11.4 to 3.11.5
  - Django from 4.2 to 5.0
  - Django CORS headers from 4.2 to 4.3
  - Django Debug toolbar from 4.1 to 4.2
  - Django Redis from 5.3 to 5.4
  - Freezegun from 1.2.1 to 1.4.0
  - Geojson from 2.5.0 to 3.1.0
  - NetCDF4 from 1.6.4 to 1.6.5
  - Psycopg2-Binary from 2.9.6 to 2.9.9
  - Sentry SDK from 1.28.1 to 1.39.2
  - uWSGI from 2.0.20 to 2.0.23
  - VCRpy from 5.0 to 5.1
  - Whitenoise from 6.5 to 6.6
  - Xarray from 2023.6.0 to 2023.12.0
  - IPython from 8.14 to 8.20
  - Py.test Django from 4.5 to 4.7


## 0.5.0 - 08/26/2023

Changes:

- API views to see which platforms have active timeseries for an ERDDAP server or dataset.
- Admin filters to select platforms by ERDDAP server, dataset, active timeseries, or standard name (data type).
- Customized the admin display for timeseries to make it more compact and collapse less useful info.

Dependency Updates:
  - Github actions
    - Setup Docker Buildx from 2.7.0 to 2.9.1
  - Pre-Commit
    - Black from 23.3.0 to 23.7.0
    - PyUpgrade from 3.7.0 to 3.9.0
    - Add trailing comma from 2.5.1 to 3.0.0
  - Python
    - Django CORS headers from 4.1 to 4.2
    - Sentry SDK from 1.25.1 to 1.28.1
    - VCRpy from 4.3 to 5.0
    - Xarray from 2023.5.0 to 2023.6.0
    - Py.Test from 7.3 to 7.4
  - Redis from 5.0.14 to 7.0.12

## 0.4.18 - 06/19/2023

Fixes:

- Attempt to to fix N+1 query from `/api/platforms/` where Django wasn't pre-fetching the timeseries for the platforms, so they were being fetched on the fly as the serializer tried to assemble the output. Fixes [#793](https://github.com/gulfofmaine/buoy_barn/issues/793)

Dependency updates:

- Pre-commit
  - Pyupgrade from 3.6.0 to 3.7.0
  - Gitleaks from 8.16.4 to 8.17.0
  - Django-upgrade from 1.13.0 to 1.14.0
- Redis from 5.0.3 to 5.0.14

## 0.4.17 - 06/19/2023

Fixes:

- Prevent duplicate datasets from being made for each server with a unique constraint. Fixes [#787](https://github.com/gulfofmaine/buoy_barn/issues/787).
- N+1 query from `/api/platforms/` where Django wasn't pre-fetching the timeseries for the platforms, so they were being fetched on the fly as the serializer tried to assemble the output. Fixes [#793](https://github.com/gulfofmaine/buoy_barn/issues/793)

Dependency updates:

- Python
  - Django Redis from 5.2 to 5.3
  - Whitenoise from 6.4 to 6.5
  - Sqlparse to 0.4.4
  - Requests to 2.31.0
  - Tornado to 6.3.2

## 0.4.16 - 06/16/2023

Fixes:

- We should continue looping through timeseries on NaN and similar index errors, rather than stopping processing them all together. [#772](https://github.com/gulfofmaine/buoy_barn/issues/772)

Dependency updates:

- Actions
  - Update runners to Ubuntu 22.04. Some were still using 18.04 which is deprecated.
  - Docker Setup Buildx from 2.4.0 to 2.7.0
  - Docker Login from 2.1.0 to 2.2.0
  - Docker Build Push from 4.0.0 to 4.1.1
  - Release from 1.2.1 to 1.4.1
- Pre-commit
  - pre-commit-hooks from 4.3.0 to 4.4.0
    - Add add `no-commit-to-branch` to prevent mistaken commits to main
  - Blackdoc from 0.3.7 to 0.3.8
  - Flake8 from 3.9.2 to 6.0.0
  - Isort from 5.10.1 to 5.12.0
  - Black from 22.10.0 to 23.3.0
  - Pyupgrade from 3.1.0 to 3.6.0
  - Add trailing comma from 2.3.0 to 2.5.1
  - Bandit from 1.7.4 to 1.7.5
  - Gitleaks from 8.15.0 to 8.16.4
  - Shellcheck from 0.8.0.4 to 0.9.0.5
  - Django Upgrade from 1.11.0 to 1.13.0
- Python
  - Python itself from 3.11.1 to 3.11.4
  - Poetry from 1.3.2 to 1.5.1
  - Celery from 5.2 to 5.3
  - Django from 4.1 to 4.2
  - Django CORS headers from 3.13 to 4.1
  - Django Debug Toolbar from 3.7 to 4.1
  - NetCDF4 from 1.6.0 to 1.6.4
  - Psycopg2 Bianry from 2.9.5 to 2.9.6
  - Sentry SDK from 1.14.0 to 1.25.1
  - VCRpy from 4.2 to 4.3
  - Whitenoise from 6.2 to 6.4
  - Xarray from 2023.1.0 to 2023.5.0
  - IPython from 8.9 to 8.14
  - Py.test from 7.2 to 7.3
  - Py.test-cov from 4.0 to 4.1
  - Prospector from 1.8 to 1.10
- Apt
  - Binutils from 2.35.2-2 to 2.40.2
  - Libproj from 7.2.1-1 to 9.1.1-1
  - Gdalbin from 3.2.2 to 3.6.2
- Added Renovate to manage dependencies that Dependabot cannot.

## 0.4.15 - 02/03/2023

Changes:

- Dependency updates:
  - Actions:
    - Docker BuildX from 2.2.1 to 2.4.0
    - Docker build push from 3.2.0 to 4.0.0
  - Poetry from 1.1.11 to 1.3.2 (lockfile changed and Dependabot is using the new one)
  - Sentry SDK from 1.8.0 to 1.14.0
  - Xarray from 2022.3.0 to 2023.1.0
  - Pandas from 1.4.3 to 1.5.3
  - IPython from 8.4 to 8.9
  - Py.test from 7.1 to 7.2
  - Prospector from 1.7 to 1.8

Fixes:

- Server proxy paths could only work with single digit server IDs. Now multiple digit id ERDDAP servers can work as proxies and not break other platforms while trying to generate the platform list. Closes [#678](https://github.com/gulfofmaine/buoy_barn/issues/678).

## 0.4.14 - 01/30/2023

Fixes

- Catch some null constraint errors. [#672](https://github.com/gulfofmaine/buoy_barn/issues/672)

## 0.4.13 - 01/06/2023

Fixes:

- Filter out healthcheck responses from Sentry transactions. [#654](https://github.com/gulfofmaine/buoy_barn/issues/654)
- Quiet some deprecation warnings. They should hopefully only yell once now in logs.

## 0.4.12-2 - 12/21/2022

Fixes:

- Missed including 408 backoff check in error handling.

## 0.4.12 - 12/21/2022

Fixes:

- Avoids scheduling additional dataset or server refreshes if there is already a refresh task in the queue. This works by when the `/refresh/` view is triggered, it instead schedules a quick task that then checks if the refresh is scheduled (or active or reserved). If it is already scheduled it throws a warning, otherwise it schedules the task.
- Add exponential backoff when timeout related errors are encountered.

## 0.4.11 - 12/20/2022

Fixes:

- Extract timeout seconds into it's own variable to get Sentry to catch it.

## 0.4.10 - 12/20/2022

Fixes:

- Add error context and adjust levels.

## 0.4.9 - 12/20/2022

Fixes:

- __Migration__ Enable per server timeouts and timing between requests. Replaces `RETRIEVE_DATAFRAME_TIMEOUT_SECONDS`.
- Fix invalid logging kwarg.
- Upgraded data retrieval logging to error to send to Sentry.
- Raise parse error when `-` is not used to split server and dataset.

## 0.4.8-2 - 12/19/2022

Fixes

- Gitops repo & CI working directory name mismatch

## 0.4.8 - 12/19/2022

Changes:

- Bumped Python to 3.11.1

Fixes:

- Catching a few more error types. Works on [#449](https://github.com/gulfofmaine/buoy_barn/issues/449) [PR](https://github.com/gulfofmaine/buoy_barn/pull/646)
  - [429 - too many requests](https://sentry.io/organizations/gulf-of-maine-research-institu/issues/2304592014/events/759b16dea027407fb936c7d510a2ebc8/?project=1373247&query=is%3Aunresolved&referrer=previous-event)
  - [404 - no matching time](https://sentry.io/organizations/gulf-of-maine-research-institu/issues/2304592014/events/0a64140872054bf6851adffba1629b40/?project=1373247&query=is%3Aunresolved&referrer=next-event)
  - [404 - no file found](https://sentry.io/organizations/gulf-of-maine-research-institu/issues/2304592014/events/1963c7c1e8d94e02be25a5f0991e155f/?project=1373247&query=is%3Aunresolved&referrer=next-event)
  - Additionally set Sentry tags on the error scope to help differentiate sources.
- Fixed continuous delivery repo and configuration.

## 0.4.7 - 12/02/2022

Changes:

- Add [Django health check](https://github.com/revsys/django-health-check) and associated Kubernetes probes to keep the uWSGI socket queue from blocking the server. [#642](https://github.com/gulfofmaine/buoy_barn/issues/642) [#8](https://github.com/gulfofmaine/buoy_barn/issues/8) and [gulfofmaine/NERACOOS-operations](https://github.com/gulfofmaine/NERACOOS-operations/issues/86)
- Bumped PyUpgrade to 3.10 with typing upgrades
- Dependency updates
  - Github Actions
    - Sentry release from 1.2.0 to 1.2.1
  - Python
    - Pytest-cov from 3.0 to 4.0

Fixes:

- Adjusted flake8 repo in pre-commit from Gitlab to Github

## 0.4.6 - 10/28/2022

Changes:

- Updated base branch from master to main
- Added pre-commit
  - Applied pre-commit changes to all files for activated hooks
  - Added Github Action workflow
  - Hooks
    - Trailing whitespace
    - Check AST
    - Check YAML
    - Check XML
    - Debug statements
    - End of file fixer
    - Check docstring
    - Large files
    - Blackdoc
    - Flake8
    - isort
    - Black
    - PyUpgrade
    - Add trailing comma
    - Bandit
    - Gitleaks
    - Shellcheck
    - Django Upgrade
- Dependency Updates
  - Github Actions
    - Setup Docker Buildx from 2.0.0 to 2.2.1
    - Docker login from 2.0.0 to 2.1.0
    - Docker Build Push from 3.0.0 to 3.2.0
    - Sentry release from 1.1.6 to 1.2.0
  - Python from 3.9.6 to 3.10.8
    - Django from 4.0 to 4.1
    - Django CORS headers from 3.12 to 3.13
    - Django Debug toolbar from 3.4 to 3.7
    - Django REST Framework from 3.13 to 3.14
    - NetCDF from 1.5.8 to 1.6.0
    - Psycopg2-binary from 2.9.3 to 2.9.5
    - Sentry SDK from 1.5.11 to 1.8.0
    - VCRpy from 4.1 to 4.2
    - Whitenoise from 6.0 to 6.2
    - Pandas from 1.4.2 to 1.4.3
    - Prefect from 1.2.1 to 1.2.3
    - IPython from 8.3 to 8.4
  - Apt
    - Binutils from 2.31.1 to 2.35.2
    - Libproj from 5.2.0 to 7.2.1
    - Gdal Bin from 2.4.0 to 3.2.2
    - Build essentials from 12.6 to 12.9
  - Updated Postgis from 10 to 15
    - This may require dumping and reloading the DB and updating the auth method.
    See [#639](https://github.com/gulfofmaine/buoy_barn/pull/639)


Fixes:

- `make down` now also stops any leftover test environment containers

## 0.4.5 - 05/10/2022

Changes:

- Added URL to ERDDAP forecast request context
- Added Sentry tag for forecast request context
- Dependency Updates:
  - Github Actions
    - Setup Docker Buildx from 1.6.0 to 2.0.0
    - Docker login from 1.14.1 to 2.0.0
    - Docker build push from 2.10.0 to 3.0.0
    - CodeQL from 1 to 2
    - CodeQL autobuild from 1 to 2
    - CodeQL analyze from 1 to 2
  - Django CORS headers from 3.11 to 3.12
  - Django Debug Toolbar from 3.2 to 3.4
  - Django Rest Framework GIS from 0.18 to 1.0
  - Sentry SDK from 1.5.8 to 1.5.11
  - Pandas from 1.4.1 to 1.4.2
  - Prefect from 1.1.0 to 1.2.1
  - IPython from 8.1 to 8.3

## 0.4.4 - 03/23/2022

Changes:

- Update Kubernetes ingress manifest to v1.
- Dependency Updates:
  - Github Actions
    - Checkout from 2.4.0 to 3
    - Cache from 2.1.7 to 3
    - Docker login from 1.14.0 to 1.14.1
    - Docker build push from 2.9.0 to 2.10.0
  - Erddapy from 1.2.0 to 1.2.1
  - Freezegun from 1.1.0 to 1.2.1
  - Sentry SDK from 1.5.6 to 1.5.8
  - xarray from 0.21.1 to 2022.3.0
  - Prefect from 1.0.0 to 1.1.0
  - Py.test from 7.0 to 7.1

## 0.4.3 - 03/01/2022

Changes:

- Update Dependencies
  - Django from 4.0.2 to 4.0.3

Fixes:

- Filter out OSErrors from uWSGI. [#529](https://github.com/gulfofmaine/buoy_barn/pull/529)
- Catch upstream forecast timeouts and handle their errors nicer. [#531](https://github.com/gulfofmaine/buoy_barn/pull/531)

## 0.4.2 - 02/28/2022

Changes:

- Move to using the newer `docker compose` compose, rather than the old `docker-compose`.
- Use API key for Prefect Cloud
- Add server and dataset ID info to timeseries refresh errors.
- Update Dependencies
  - Actions
    - Checkout from 2.3.5 to 2.4.0
    - Cache from 2.1.6 to 2.1.7
    - Docker login from 1.10.0 to 1.14.0
    - Docker build push from 2.7.0 to 2.9.0
  - Celery from 5.1 to 5.2
  - Django from 3.2 to 4.0
  - Django CORS headers from 3.8 to 3.11
  - Django Redis from 5.0 to 5.2
  - Django Rest Framework from 3.12 to 3.13
  - Django Rest Framework GIS from 0.17 to 0.18
  - ERDDAPy from 1.1.0 to 1.2.0
  - NetCDF4 from 1.5.7 to 1.5.8
  - Psycopg2 binary from 2.9.1 to 2.9.3
  - Sentry SDK from 1.4.3 to 1.5.6
  - Uwsgi from 2.0.19 to 2.0.20
  - Whitenoise from 5.3 to 6.0
  - Xarray from 0.19.0 to 0.21.1
  - Pandas from 1.3.3 to 1.4.1
  - Prefect from 0.15.6 to 1.0.0
  - IPython from 7.28 to 8.1
  - Py.test from 6.2 to 7.0
  - Py.test Django from 4.4 to 4.5
  - Prospector from 1.3 to 1.7

Fixes:

- Remove rogue breakpoint

## 0.4.1 - 10/26/2021

- Update Dependencies:
  - Actions
    - Checkout from 2.3.4 to 2.3.5
    - Setup Docker Buildx from 1.5.1 to 1.6.0
    - Docker build push from 2.6.1 to 2.7.0
  - Poetry from 1.1.5 to 1.1.11
  - Django CORS headers from 3.7 to 3.8
  - Sentry SDK from 1.3.1 to 1.4.3
  - Pandas from 1.3.1 to 1.3.3
  - Prefect from 0.15.3 to 0.15.6
  - IPython from 7.26 to 7.28
  - PYYaml from 5.4 to 6.0
  - py.test coverage from 2.12 to 3.0

Fixes:

- Adds a timeout to proxied requests. Closes #457
  - Timeout can be set with the environment variable `PROXY_TIMEOUT_SECONDS` and defaults to 30 seconds.

## 0.4.0 - 08/12/2021

Additions:

- Smart CORS proxying through Buoy Barn.
  - Previously when CORS requests needed to be proxied for Mariners Dashboard, Buoy Barn will mark those servers as needing a proxy and host an endpoint to proxy through.
  - Adds a `cors_proxy_url` key to readings for servers that need a proxy. The value is the base URL for the server (aka, `buoybarn.neracoos.org/api/servers/1/proxy/` forwards to `neracoos.org/erddap/`).
  - Proxied data is cached by default for 60 seconds, but that can be overridden with `PROXY_CACHE_SECONDS`.

Changes:

- Update Dependencies:
  - Actions
    - Setup Docker Buildx from 1 to 1.5.1
    - Cache from 2.1.5 to 2.1.6
    - Docker login from 1 to 1.10.0
    - Docker build push from 2 to 2.6.1
    - Sentry release from 1 to 1.1.6
  - Python from 3.9.4 to 3.9.6
  - Celery from 5.0 to 5.1
  - Django Redis from 4.12 to 5.0
  - NetCDF4 from 1.5.6 to 1.5.7
  - Psycopg2 Binary from 2.8.6 to 2.9.1
  - Sentry SDK from 1.0.0 to 1.3.1
  - Whitenoise from 5.2 to 5.3
  - Xarray from 0.17.0 to 0.19.0
  - Pandas from 1.2.4 to 1.3.1
  - Prefect from 0.14.15 to 0.15.3
  - IPython from 7.22 to 7.26
  - Py.test Django from 4.2 to 4.4
  - Py.test Coverage from 2.11 to 2.12

Fixes:

- Match Sentry release to Github release version.

## 0.3.6 - 04/19/2021

Changes:

- Add non-standard datatypes for UNH buoys. [#351](https://github.com/gulfofmaine/buoy_barn/pull/351)
- Update Dependencies:
  - Actions
    - Cache from 2.1.4 to 2.1.5
  - Python from 3.9.2 to 3.9.4
  - Django from 3.1 to 3.2
  - erddapy from 0.9.0 to 1.0.0
  - Pandas from 1.2.3 to 1.2.4
  - Prefect from 0.14.14 to 0.14.15
  - Pytest Django from 4.1 to 4.2

Fixes:

- Add `DEFAULT_AUTO_FIELD` setting to point to little integer autofield as Django will be migrating to BigAutoField. [#351](https://github.com/gulfofmaine/buoy_barn/pull/351)

## 0.3.5 - 03/29/2021

Changes:

- Enable [Sentry Performance Monitoring](https://docs.sentry.io/product/performance/) for a subset of transactions.
- Enhance Sentry Releases using Github Action.
- Update Dependencies:
  - Sentry SDK from 0.20.3 to 1.0.0
  - Xarray from 0.16.2 to 0.17.0
  - Pandas from 1.2.2 to 1.2.3
  - Prefect from 0.14.11 to 0.14.14
  - IPython from 7.21 to 7.22

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
