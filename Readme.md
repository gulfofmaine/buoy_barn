# Buoy Barn [![Semaphore Dashboard](https://img.shields.io/badge/Semaphore-Dashboard-lightgrey.svg)](https://gmri.semaphoreci.com/projects/Neracoos-1-Buoy-App) [![Codacy Badge](https://api.codacy.com/project/badge/Grade/76fde26fc3c54127bba8075b3ea9da99)](https://www.codacy.com?utm_source=github.com&utm_medium=referral&utm_content=gulfofmaine/buoy_barn&utm_campaign=Badge_Grade) [![Codacy Badge](https://api.codacy.com/project/badge/Coverage/76fde26fc3c54127bba8075b3ea9da99)](https://www.codacy.com?utm_source=github.com&utm_medium=referral&utm_content=gulfofmaine/buoy_barn&utm_campaign=Badge_Coverage)

Lightweight ERDDAP frontend API for NERACOOS buoy information, recent readings, and for generating point forecasts from different model sources.

## Usage

If you are setting it up for the first time see [Initial Configuration](#initial-configuration) down below.

Otherwise you can use `make up` to start the server, which you can then access the admin at [localhost:8080/admin/](http://localhost:8080/admin/) and api at [localhost:8080/api/](http://localhost:8080/api/).

You can also launch it quickly in your current Kubernetes cluster. See [Kubernetes](#kubernetes) below

There are two ways to refresh data.

- First, you can refresh the values for a specific dataset.
  This is designed to work with the ERDDAP subscription service, allowing the ERDDAP server to notify Buoy Barn when there is new data, which is more efficient than refreshing on a schedule.

  - First navagate to `datasets/` in the API, then find the slug of the dataset that should be refreshed.
    Append that value to `datasets/` and then you can add `refresh/` after that, so `/api/datasets/<SLUG>/refresh/` will trigger the dataset to update the associated timeseries data.

  - Then go to the erddap server that contains the dataset, say Coastwatch, and find the subscription service (it should be on the home page).
    From the [add page](https://coastwatch.pfeg.noaa.gov/erddap/subscriptions/add.html), you can then enter the dataset ID, your email, and the URL that you just found previously to subscribe to updates.

- Second, you can refresh all timeseries from a specific server.
  This is for timeseries that do not use the ERDDAP subscription service.

If you `ctrl-c` out of the logs (or close the window), you can get the logs back with `make logs`.

The Docker containers are launched in the background with `make up`, so they won't dissapear if you close the window or logs.
Therefore when you are done, `ctrl-c` out of the logs and run `make down` to shut down the server and database.

### Forecasts

See [forecasts/Readme.md](app/forecasts/Readme.md) for details about how the forecasts API works and how to add new forecasts.

### Adding / Editing Platforms

To add or edit a platform (buoy) go to [admin/deployments/platform](http://localhost:8080/admin/deployments/platform/).
From there you can add or edit a platform.

See below for adding a timeseries to a platform.

### Adding a Deployment

If you wish to keep track of deployments for particular platforms, you can manage them at [admin/deployments/platform](http://localhost:8080/admin/deployments/platform/).

### Adding new TimeSeries

You can manage different which TimeSeries are associated with a Platform from the admin, or you can attempt to automatically add them from the python shell.

Lets use the automatic loader.

From a dataset page (for example [N01 Sbe](http://www.neracoos.org/erddap/tabledap/N01_sbe37_all.html)) the first thing to do is figure out our constraints.

For this we are worried about a specific depth, so let's choose that from the dropdown.
You'll notice the optional constraint 1 for depth has changed to an `=` and our depth is in the field next to it.

We don't need to worry about time as a constraint, the loader will automatically find that.
In some cases we may need to select a specific station, but we don't need to do that here.

We pass our constraints as a dict with the key being the variable and the `=` sign, and the value being the selected value.
Therefore our constraints are `{'depth=': 50.0}`.

To do that we will use `add_timeseries(platform, erddap_url, dataset, constraints)`.

- `platform` takes a `Platform` instance
- `erddap_url` takes the base url for the ERDDAP server
- `dataset` takes the Dataset ID
- `constraints` uses the constraints that you just figured out

Now with a shell (`make shell`).

```python
>>> from deployments.utils.erddap_loader import add_timeseries
>>> from deployments.models import Platform

>>> n01 = Platform.objects.get(name='N01')

>>> add_timeseries(n01, 'http://www.neracoos.org/erddap', 'N01_accelerometer_all', {'depth=': 50.0})
```

`add_timeseries` will retireve the dataset info, figure out the time range the dataset is valid for, find which variables are avaliabe, find or create data_types for those variables, and add the `TimeSeries` to the given platforms.

## Testing

Tests can be run with `make test`.
Django will initialize a new database, run migrations, run tests in transactions, and then delete the database.
Tests that attempt to access external servers (for getting ERDDAP data) should be mocked out using [VCR](https://vcrpy.readthedocs.io/en/latest/) to make sure they are more repeatable despite network, server, or dataset issues.

Automated tests are run after code is pushed to GitHub by [Semaphore](https://vcrpy.readthedocs.io/en/latest/), and test status is indicated on pull requests.

[Codacy](https://app.codacy.com/project/gmri/buoy_barn/dashboard) automatically checks for code quality and test coverage.

### Test Coverage

Tests coverage can be run with `make coverage`.
After the tests are run, and the report displayed in the command line, it will also generate an html report.
This report can be viewed by opening `app/htmlcov/index.html` which will also attempt to automatically open in the default browser.

## Initial Configuration for Development

### Settings

To start the database, you'll need to configure it with a username and password. You'll also need to set a secret key that Django will use to protect sessions.

Redis also runs as a cache and a task queue, and the uri to the cache instance should be included.

To do so create a `secret.env` file in `./docker-data/` that looks something like this.

```bash
POSTGRES_PASSWORD=secret_string
POSTGRES_USER=a_user_name
SECRET_KEY=a_really_long_random_string_that_no_one_should_no_and_should_probably_be_gibberish
REDIS_CACHE=rediss://cache:6379/0
DJANGO_DEBUG=True
DJANGO_MANAGEPY_MIGRATE=off
SENTRY_DSN=some_long_string_from_sentry
CELERY_BROKER_URL=rediss://cache:6379/1
PREFECT__CLOUD__AUTH_TOKEN=tenant_token
PREFECT__CLOUD__AGENT__AUTH_TOKEN=runner_token
PREFECT_PROJECT_NAME=project_that_the_prefect_flows_should_be_registered_to
```

An additional environment variable is currently configured in `docker-compose.yaml` as it is unlikely to need to be changed.

There are additionally two environment variables for changing the timeout when
querying ERDDAP servers.
`RETRIEVE_FORECAST_TIMEOUT_SECONDS` and `RETRIEVE_DATAFRAME_TIMEOUT_SECONDS`.

`SENTRY_TRACES_SAMPLE_RATE` can be used to set what percentage of requests are [performance traced and sent to Sentry](https://docs.sentry.io/platforms/python/guides/django/performance/). Defaults to 0 if not set.

### Starting Docker

Then you can use `make up` to start the database and Django server.
Docker will take a few min to download and build the containers for the database and server.

Once the database and server are started, you'll need to run `make migrate` to get the database structure in place.

### Create an account

To create an administrator account run `make user` and follow the prompts.

Once you have an account setup, you'll be able to login to the admin at [localhost:8080/admin/](http://localhost:8080/admin/).

### Bulk Loading and Dumping Data

You can use Django fixtures to quickly save models from the database and reload them.
`make dump` will save most of the `deployment` related models to `/app/dump.json`, which you can load with `make load`.

## Structure

- `app/`
  - `account/` Django user account app.
  - `buoy_barn/` Primary Django application.
  - `deployments/` Database models and API.
  - `forecasts/` Forecast models and API.
  - `utils/`
    - `wait-for-it.sh` Shell script that can wait until specified services are avaliable before finishing. Helps `make up` launch Django more reliably.
  - `Dockerfile` Django server build steps
  - `manage.py` Django management script
  - `requirements.txt` Python package requirements
- `docker-data/`
  - `postgres/` Database storage
  - `secret.env` Environment variables to manage database connection and similar configuration.
- `.gitignore` Files that should be ignored by git
- `.prospector.yaml` Linting configuration
- `docker-compose.yaml` Database and server docker container configuration
- `Makefile` Common commands made easier to remember.
- `Readme.md` You are here.

## Make commands

- `build` Builds containers in parallel
- `up` Builds and starts Docker containers before following the logs.
- `down` Stops and removed Docker containers.
- `stop` Stops Docker containers.
- `logs` Follow logs for currently running Docker containers.
- `migrations` Attempt to auto-detect and create new migrations for any Django models that have new fields.
- `migrate` Run database migrations
- `prune` Clear out old Docker layers and containers systemwide (not just this project)
- `fixtures` Dump Deployments models to `/app/deployments/fixtures/`
- `load` Load Django fixtures in `/app/deployments/fixtures/*.yaml`
- `user` Create a new Django admin/super user.
- `shell` Launch a Python shell from the Django `manage.py`
- `test` Run unit tests.
- `requirements-compile` Take the high level requirements files generate a pinned requirements.txt file.
- `requirements-tree` See the dependency tree of the requirements and any issues.
- `lint` Run prospector (and associated linting tools).

## Common Tasks and Problems

### Migrations

Django may let you know that your database is not up to date with all the migrations.

```python
System check identified 1 issue (0 silenced).

You have 1 unapplied migration(s). Your project may not work properly until you apply the migrations for app(s): deployments.
```

Run `make migrate` to run any outstanding migrations.

### Django throwing errors on start

Often the Django server can be ready before the database is due to the database catching up and making sure everything is committed before allowing access.

In order to try to avoid that `wait-for-it.sh` is run before `python manage.py runserver` that tries to wait for the database to become avaliable.

This takes care of things most of the time, but sometimes the database will look avaliable to `wait-for-it.sh` (it depends on if a port is open, and Postgres opens the port at a specific stage in recovery to report status).

If this does occur (look for `psycopg` in the errors), just open and save `app/manage.py` to get the server to try to reload.
It works to hit save in most other `.py` files under the `app/` directory as well.

## Kubernetes

As we are moving towards using Kubernetes, you can launch Buoy Barn in a Kubernetes cluster.
See the `/k8s/` directory to see the configs.

Once those are set up, you can run `skaffold dev` to launch a easily interactive version of the cluster.
Use `ctrl-c` to shutdown the cluster, and [Skaffold](https://skaffold.dev) will tear down what it set up.

To deploy, use `skaffold run -t VERSION_NUMBER --tail` when connected to the NERACOOS Kubernetes cluster.
