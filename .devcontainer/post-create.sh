#!/usr/bin/env bash
# First-run bootstrap for the dev container. Idempotent: safe to re-run, and it
# skips seeding when the (persisted) database already has data.
set -euo pipefail

# Work from the Django project directory regardless of where we're invoked from.
cd "$(dirname "$0")/../app"

echo "==> Installing Python dependencies (uv sync)"
uv sync

echo "==> Applying database migrations"
uv run manage.py migrate --noinput

# Seed fixtures only when the database has no platforms yet, so rebuilds against
# the persisted data directory don't re-import on every container start.
platform_count="$(uv run manage.py shell -c \
  'from deployments.models import Platform; print(Platform.objects.count())' \
  2>/dev/null | tail -n 1 | tr -d '[:space:]')"

if [ "${platform_count:-0}" = "0" ]; then
  echo "==> Seeding database from fixtures"
  uv run manage.py loaddata \
    deployments/fixtures/platforms.yaml \
    deployments/fixtures/Alerts.yaml \
    deployments/fixtures/datatypes.yaml \
    deployments/fixtures/deployments.yaml \
    deployments/fixtures/erddapservers.yaml \
    deployments/fixtures/ErddapDataset.yaml \
    deployments/fixtures/programs.yaml \
    deployments/fixtures/platformattribution.yaml \
    deployments/fixtures/TimeSeries.yaml
else
  echo "==> Database already has ${platform_count} platform(s); skipping fixtures"
fi

# Create a default admin user only if one does not already exist.
admin_exists="$(uv run manage.py shell -c \
  'from django.contrib.auth import get_user_model; print(get_user_model().objects.filter(username="admin").exists())' \
  2>/dev/null | tail -n 1 | tr -d '[:space:]')"

if [ "${admin_exists}" = "True" ]; then
  echo "==> Superuser 'admin' already exists; skipping"
else
  echo "==> Creating default superuser (admin / admin)"
  DJANGO_SUPERUSER_PASSWORD="admin" uv run manage.py createsuperuser \
    --noinput --username admin --email admin@example.com
fi

cat <<'EOF'

Dev container ready.
  Start the server:  cd app && uv run manage.py runserver 0:8090
  Admin:  http://localhost:8090/admin/   (login: admin / admin)
  API:    http://localhost:8090/api/
EOF
