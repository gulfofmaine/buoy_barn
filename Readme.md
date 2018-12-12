Buoy Barn
=========

Lightweight ERDDAP frontend API for NERACOOS buoy information and recent readings.

## Usage

If you are setting it up for the first time see [Initial Configuration](#initial-configuration) down below.

Otherwise you can use `make up` to start the server, which you can then access the admin at [localhost:8080/admin/](http://localhost:8080/admin/) and api at [localhost:8080/api/](http://localhost:8080/api/).

If you `ctrl-c` out of the logs (or close the window), you can get the logs back with `make logs`.

The Docker containers are launched in the background with `make up`, so they won't dissapear if you close the window or logs. Therefore when you are done, `ctrl-c` out of the logs and run `make down` to shut down the server and database.

### Adding / Editing Platforms

To add or edit a platform (buoy) go to [admin/deployments/platform](http://localhost:8080/admin/deployments/platform/).
From there you can add or edit a platform.

See below for adding a timeseries to a platform.

### Adding a Deployment

If you wish to keep track of deployments for particular platforms, you can manage them at [admin/deployments/platform].

### Adding new TimeSeries

You can manage different which TimeSeries are associated with a Platform from the admin, or you can attempt to automatically add them from the python shell.

## Testing

Tests can be run with `make test`.
Django will initialize a new database, run migrations, run tests in transactions, and then delete the database.

### Test Coverage

Tests coverage can be run with `make coverage`.
After the tests are run, and the report displayed in the command line, it will also generate an html report.
This report can be viewed by opening `app/htmlcov/index.html` which will also attempt to automatically open in the default browser.

## Initial Configuration

### Settings

To start the database, you'll need to configure it with a username and password. You'll also need to set a secret key that Django will use to protect sessions.

To do so create a `secret.env` file in `./docker-data/` that looks something like this.

```
POSTGRES_PASSWORD=secret_string
POSTGRES_USER=a_user_name
SECRET_KEY=a_really_long_random_string_that_no_one_should_no_and_should_probably_be_gibberish
```

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
  - `account/` - Django user account app.
  - `buoy_barn/` - Primary Django application.
  - `deployments/` - Database models and API.
  - `utils/`
    - `wait-for-it.sh` - Shell script that can wait until specified services are avaliable before finishing. Helps `make up` launch Django more reliably.
  - `Dockerfile` - Django server build steps
  - `manage.py` - Django management script
  - `requirements.txt` - Python package requirements
- `docker-data/`
  - `postgres/` - Database storage
  - `secret.env` - Environment variables to manage database connection and similar configuration.
- `.gitignore` - Files that should be ignored by git
- `.prospector.yaml` - Linting configuration
- `docker-compose.yaml` - Database and server docker container configuration
- `Makefile` - Common commands made easier to remember.
- `Readme.md` - You are here.

## Make commands

- `build` - Builds containers in parallel
- `up` - Builds and starts Docker containers before following the logs.
- `down` - Stops and removed Docker containers.
- `stop` - Stops Docker containers.
- `logs` - Follow logs for currently running Docker containers.
- `migrations` - Attempt to auto-detect and create new migrations for any Django models that have new fields.
- `migrate` - Run database migrations
- `prune` - Clear out old Docker layers and containers systemwide (not just this project)
- `dump` - Dump Deployments database instances to `/app/dump.json`
- `load` - Load Django fixtures in `/app/dump.json`
- `user` - Create a new Django admin/super user.
- `shell` - Launch a Python shell from the Django `manage.py`
- `test` - Run unit tests.

## Common Problems

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
