# Deploying the observability changes

This repository's `k8s/` directory is a **reference implementation**. Argo CD deploys from
[`gulfofmaine/neracoos-aws-cd`](https://github.com/gulfofmaine/neracoos-aws-cd), so the
changes below have to be made there too.

See [observability.md](./observability.md) for what is exported and why.

## Checklist

### 1. Configuration

Add to the config map (mirrors `k8s/base/config.env`):

```
OTEL_SERVICE_NAME=buoy-barn
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.observability:4318
```

Correct the endpoint to whatever the cluster's collector actually is. **Until this is set,
every metric in the application is a no-op** — that is deliberate, so a partial rollout
degrades to the previous behaviour instead of erroring.

### 2. Per-deployment role

Add `BUOY_BARN_OTEL_ROLE` to each deployment so metrics can be split by process type:

| Deployment | Value |
| --- | --- |
| `web` | `web` |
| `worker` | `worker` |
| `beat` | `beat` |
| `flower` | `flower` |
| mqtt (if deployed) | `mqtt` |
| `metrics-exporter` | `exporter` |

It is guessed from the command line if unset, but setting it explicitly is cheaper than
debugging a wrong guess.

### 3. New `metrics-exporter` deployment

Port `k8s/base/metrics-exporter.yaml`. It runs `manage.py export_metrics`, which serves the
database-derived freshness gauges and Celery queue depth.

Two properties are load-bearing:

- **`replicas: 1`.** These are gauges describing database state, so a second replica reports
  every series twice.
- **`strategy: Recreate`.** A rolling update would briefly run two pods, with the same
  double-counting effect.

It also sets `DJANGO_MANAGEPY_MIGRATE: "off"`: this pod is not part of the deploy ordering,
and the web/worker/beat pods already contend for migrations on every rollout.

### 4. Secrets

Add `WEEKLY_OLD_TIMESERIES_HEALTHCHECK_URL` — the Healthchecks.io monitor for the weekly
stale-timeseries task, which previously had no monitor.

### 5. Confirm the collector accepts metrics

The cluster collector must have a **metrics** pipeline, not just traces:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  prometheus:
    endpoint: 0.0.0.0:8889
    # Without this, gauges for retired timeseries and deleted datasets are exported
    # forever. Series stop being reported when they stop being observed, so let them age out.
    metric_expiration: 5m
service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [prometheus]
```

Then confirm Prometheus scrapes the collector's `prometheus` exporter endpoint. Application
pods are **not** scrape targets — they push. This is why: granian runs 4 worker processes and
the Celery worker forks a child per CPU, so an in-process `/metrics` endpoint could only ever
show one process out of many.

### 6. Healthchecks.io — do not skip this

Configure both monitors with a schedule and grace period, or a missed beat tick never alerts:

| Monitor | Schedule |
| --- | --- |
| hourly refresh (`HOURLY_REFRESH_HEALTHCHECK_URL`) | `5 * * * *` |
| weekly stale timeseries (`WEEKLY_OLD_TIMESERIES_HEALTHCHECK_URL`) | weekly, Mondays ~15:00 UTC |

Grace periods should exceed the task's normal runtime. The hourly refresh fans out to every
stale dataset, so give it room.

### 7. Optional: start using the Sentry traces you already pay for

`SENTRY_TRACES_SAMPLE_RATE` defaults to `0`, so the span data that `CeleryIntegration` and
`DjangoIntegration` already produce is being discarded. Set it to e.g. `0.1`.

## Verifying the rollout

1. `kubectl logs deploy/worker` should show `OpenTelemetry metrics enabled (role=worker, ...)`
   once per prefork child. Only the parent logging it means the child initialisation is not
   working, and metrics will be silently discarded.
2. In Prometheus, `buoybarn_celery_task_count` should be non-zero within a couple of export
   intervals (default 60s).
3. `buoybarn_dataset_refresh_age` should have roughly one series per dataset. If it is empty,
   check the `metrics-exporter` pod; if it has double the expected series, check it is at one
   replica.
4. `buoybarn_erddap_outcome` split by `outcome` is the dashboard worth building first — it is
   the only place a permanently failing dataset shows up, since the Celery task reports
   success either way.

## Rolling back

Unset `OTEL_EXPORTER_OTLP_ENDPOINT`. Every metric call becomes a no-op with no exporter
threads and no network traffic; the application behaves exactly as it did before. The
`metrics-exporter` deployment will log that there is nothing to export and exit rather than
crash-looping, so it can be scaled to zero at leisure.
