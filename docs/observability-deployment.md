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

### 6. Healthchecks.io

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

## Metric names in Prometheus

The instrument names in the code are dotted OTel names; the collector's `prometheus` exporter
rewrites them. Worth knowing before writing any query:

- Dots become underscores: `buoybarn.erddap.outcome` → `buoybarn_erddap_outcome`.
- **Counters gain `_total`**: `buoybarn_erddap_outcome_total`.
- **A `s` unit becomes `_seconds`**: `buoybarn.erddap.request.duration` →
  `buoybarn_erddap_request_duration_seconds`, with the usual `_bucket` / `_sum` / `_count`
  histogram series. Annotation-only units like `{row}` are dropped, so
  `buoybarn.erddap.request.rows` stays `buoybarn_erddap_request_rows_*`.
- Attribute keys are underscored the same way: `erddap.server` → `erddap_server`,
  `celery.task` → `celery_task`, `timeseries.type` → `timeseries_type`.
- **Resource attributes do not become labels.** `service.name` and `service.instance.id`
  become `job` and `instance`; everything else, including `buoybarn.role`, lands on the
  `target_info` metric. To filter by role, join through it:

  ```promql
  buoybarn_celery_task_count_total
    * on (job, instance) group_left(buoybarn_role) target_info
  ```

  Do **not** reach for `resource_to_telemetry_conversion: true` to avoid that join: it would
  promote `service.instance.id` to a label as well, multiplying every series by the number of
  granian workers and prefork children. Most queries below do not need the role — the
  `celery_task` and `erddap_server` labels are enough.

Confirm the exact names against the collector's own metrics endpoint once before building
dashboards; translation defaults do shift between collector versions.

## Verifying the rollout

**1. Every process is exporting, including the Celery prefork children.** This is the check
that matters most, because getting it wrong fails silently rather than loudly.

```promql
count(count by (instance) (buoybarn_celery_task_count_total))
```

Each granian worker and each prefork child has its own `service.instance.id`, so this should
be well above 1. `kubectl logs deploy/worker` should likewise show
`OpenTelemetry metrics enabled (role=worker, ...)` once per child — a single line from the
parent only means the child initialisation is not working and metrics are being discarded.

**2. Task metrics are flowing.**

```promql
sum by (celery_task, celery_state) (rate(buoybarn_celery_task_count_total[5m]))
```

Non-zero within a couple of export intervals (60s default).

**3. The freshness exporter is up, and running exactly once.**

```promql
count(buoybarn_dataset_refresh_age_seconds)
```

Should be roughly one series per dataset (~384). Empty means the `metrics-exporter` pod is not
running; double the expected count means it is running more than one replica.

**4. Failing datasets are visible.** Build this dashboard first — it is the only place a
permanently broken dataset shows up, since the Celery task reports success either way.

```promql
# Which datasets are failing, and how
sum by (erddap_server, erddap_dataset, outcome) (
  increase(buoybarn_erddap_outcome_total{outcome!="success"}[1h])
) > 0

# Overall failure ratio per server
1 - (
  sum by (erddap_server) (rate(buoybarn_erddap_outcome_total{outcome="success"}[1h]))
  / sum by (erddap_server) (rate(buoybarn_erddap_outcome_total[1h]))
)

# A failure shape nobody has written a handler for -- worth alerting on
sum by (erddap_dataset) (increase(buoybarn_erddap_outcome_total{outcome="unknown_error"}[6h])) > 0
```

## Queries worth keeping

**Stale data** — `agg="min"` is the age of the *freshest* reading, i.e. "is this buoy
reporting at all":

```promql
max by (platform) (buoybarn_timeseries_value_age_seconds{agg="min"}) > 86400

# Datasets not refreshed in over two hours, against a nominally hourly schedule
max by (erddap_server, erddap_dataset) (buoybarn_dataset_refresh_age_seconds) > 7200
```

**Upstream latency**, to find the servers worth throttling or contacting:

```promql
histogram_quantile(0.95,
  sum by (le, erddap_server) (rate(buoybarn_erddap_request_duration_seconds_bucket[30m]))
)
```

**Task runtime against the 1800s hard limit** — `refresh_server` is the one to watch:

```promql
histogram_quantile(0.99,
  sum by (le, celery_task) (rate(buoybarn_celery_task_duration_seconds_bucket[6h]))
)
```

**Backlog and stuck tasks:**

```promql
buoybarn_celery_queue_depth

histogram_quantile(0.95,
  sum by (le, celery_task) (rate(buoybarn_celery_task_queue_latency_seconds_bucket[30m]))
)

# In-progress stays above zero while nothing completes -> wedged worker
sum by (celery_task) (buoybarn_celery_task_in_progress) > 0
  and sum by (celery_task) (increase(buoybarn_celery_task_count_total{celery_state="success"}[30m])) == 0
```

**Silently failing Healthchecks.io pings** — every ping call site swallows its exception, so
without this a monitor that stopped being pinged looks identical to a healthy one:

```promql
sum by (monitor) (increase(buoybarn_healthcheck_ping_total{outcome="error"}[1d])) > 0
```

**Error log volume by module**, the coarse backstop for anything the outcome counter misses:

```promql
sum by (logger) (rate(buoybarn_log_records_total{level="error"}[1h]))
```

## Rolling back

Unset `OTEL_EXPORTER_OTLP_ENDPOINT`. Every metric call becomes a no-op with no exporter
threads and no network traffic; the application behaves exactly as it did before. The
`metrics-exporter` deployment will log that there is nothing to export and exit rather than
crash-looping, so it can be scaled to zero at leisure.
