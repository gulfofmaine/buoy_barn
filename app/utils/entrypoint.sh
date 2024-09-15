#!/bin/sh

# from https://www.caktusgroup.com/blog/2017/03/14/production-ready-dockerfile-your-python-django-app/
# entrypoint design

set -e

until uv run manage.py db_ready; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 1
done

>&2 echo "Postgres is up - continuing"

if [ "$DJANGO_MANAGEPY_MIGRATE" = 'on' ]; then
    uv run manage.py migrate --noinput
fi

if [ "$DJANGO_MANAGEPY_COLLECTSTATIC" = 'on' ]; then
    uv run manage.py collectstatic --noinput
fi

exec "$@"
