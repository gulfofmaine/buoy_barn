# CHANGELOG

## Upcoming (unknown release)

Additions:

Changes:

- Test using Github Actions.
- Replace Pip-tools with Poetry for dependency management.
- Usepy.test to manage testing

Fixes:

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
