#syntax=docker/dockerfile:1.23
# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:b3b7ad909281e78785cbc676c8c8b45816c31638b36dc0cbd9e51725f2f0399c AS base

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

# Development container stage: adds a non-root user and interactive tooling.
# The Dev Containers spec / Claude Code feature require a non-root remoteUser,
# which also lets Codespaces remap the user's UID onto the bind-mounted workspace.
# No ENTRYPOINT/CMD - the devcontainer compose runs `sleep infinity`.
FROM base AS devcontainer

ARG USERNAME=vscode

RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    sudo \
    ca-certificates \
    && groupadd --gid 1000 ${USERNAME} \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash ${USERNAME} \
    && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
    && chmod 0440 /etc/sudoers.d/${USERNAME}

WORKDIR /workspaces

# Production stage. Kept last so the default build target (used by
# docker-compose.test.yaml and `make build`) resolves to the production image.
FROM base AS production

RUN groupadd granian && useradd -g granian granian

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

RUN chown -R granian:granian /app

ENTRYPOINT ["/app/utils/entrypoint.sh"]

CMD ["uv", "run", "granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8080", "--workers", "4", "buoy_barn.asgi:application"]
