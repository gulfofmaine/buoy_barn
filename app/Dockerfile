#syntax=docker/dockerfile:1.6
FROM python:3.12.1-slim@sha256:c805c5edcf6005fd72f933156f504525e1da263ffbc3fae6b4940e6c360c216f

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Don't write bytecode
ENV PYTHONDONTWRITEBYTECODE 1
# Show deprication warnings https://docs.djangoproject.com/en/2.2/howto/upgrade-version/#resolving-deprecation-warnings
ENV PYTHONWARNINGS once
# Do not use virtualenv with Poetry
ENV POETRY_VIRTUALENVS_CREATE false

# geodjango spatial requirements
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    binutils=2.40-2 \
    libproj-dev=9.1.1-1+b1 \
    gdal-bin=3.6.2+dfsg-1+b2 \
    build-essential=12.9

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install poetry==1.5.1 \
    && groupadd uwsgi && useradd -g uwsgi uwsgi

# Working directory
RUN mkdir /app
WORKDIR /app

# Install requirements
COPY ./pyproject.toml ./poetry.lock /app/
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry install --no-interaction

# Copy app to working directory
COPY ./ /app/

RUN chown -R uwsgi:uwsgi /app

ENTRYPOINT ["/app/utils/entrypoint.sh"]

CMD ["uwsgi", "--http", ":8080", "--wsgi-file", "buoy_barn/wsgi.py", "--master", "--processes", "4", "--threads", "2", "--uid", "uwsgi", "--gid", "uwsgi"]
