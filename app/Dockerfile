#syntax=docker/dockerfile:1.22
# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:abc097534bf1c917a8ed6408e28c87cf191560c4da3ced2016bf8b9da74b5831

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Show deprication warnings https://docs.djangoproject.com/en/2.2/howto/upgrade-version/#resolving-deprecation-warnings
ENV PYTHONWARNINGS once
# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# geodjango spatial requirements
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    binutils=2.44-3 \
    libproj-dev=9.6.0-1 \
    gdal-bin=3.10.3+dfsg-1 \
    build-essential=12.12

RUN groupadd uwsgi && useradd -g uwsgi uwsgi

# Working directory
RUN mkdir /app
WORKDIR /app

# Install requirements
COPY ./pyproject.toml ./uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Copy app to working directory
COPY ./ /app/

RUN chown -R uwsgi:uwsgi /app

ENTRYPOINT ["/app/utils/entrypoint.sh"]

CMD ["uv", "run", "uwsgi", "--http", ":8080", "--wsgi-file", "buoy_barn/wsgi.py", "--master", "--processes", "4", "--threads", "2", "--uid", "uwsgi", "--gid", "uwsgi"]
