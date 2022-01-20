#syntax=docker/dockerfile:1.2
FROM python:3.10.2-slim@sha256:ca2a31f21938f24bab02344bf846a90cc2bff5bd0e5a53b24b5dfcb4519ea8a3

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Don't write bytecode
ENV PYTHONDONTWRITEBYTECODE 1
# Show deprication warnings https://docs.djangoproject.com/en/2.2/howto/upgrade-version/#resolving-deprecation-warnings
ENV PYTHONWARNINGS always
# Do not use virtualenv with Poetry
ENV POETRY_VIRTUALENVS_CREATE false

# geodjango spatial requirements
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    binutils=2.31.1-16 \
    libproj-dev=5.2.0-1 \
    gdal-bin=2.4.0+dfsg-1+b1 \
    build-essential=12.6

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install poetry==1.1.11 \
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
