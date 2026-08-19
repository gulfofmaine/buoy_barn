# Deploying the observability changes

`k8s/base/` in this repository is the kustomize base that
[`gulfofmaine/neracoos-aws-cd`](https://github.com/gulfofmaine/neracoos-aws-cd) extends, so
everything this PR adds to those manifests — the `OTEL_*` config, `BUOY_BARN_OTEL_ROLE` on
each deployment, and the new `metrics-exporter` — flows through to the overlay automatically.
Nothing needs re-creating there.

See [observability.md](./observability.md) for what is exported and why.

## What still has to be done in the deploy repo

Four things, none of which the base can supply.

### 1. Point at the real collector

`k8s/base/config.env` carries a placeholder:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.observability:4318
```

Patch it in the overlay to the cluster's actual collector address. **Until it resolves,
every metric in the application is a no-op** — deliberately, so a partial rollout degrades to
the previous behaviour instead of erroring.

### 2. Add the new secret

`WEEKLY_OLD_TIMESERIES_HEALTHCHECK_URL` — the Healthchecks.io monitor for the weekly
stale-timeseries task, which previously had no monitor at all. It belongs in
`buoy-barn-secrets` alongside `HOURLY_REFRESH_HEALTHCHECK_URL`.

### 3. Confirm the collector has a metrics pipeline

Traces alone are not enough; it needs to accept OTLP **metrics** and export them to
Prometheus:

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

Prometheus scrapes the collector's `prometheus` exporter endpoint. Application pods are
**not** scrape targets — they push. This is why: granian runs 4 worker processes and the
Celery worker forks a child per CPU, so an in-process `/metrics` endpoint could only ever
show one process out of many.

### 4. Configure the Healthchecks.io monitors

Both monitors need a schedule and a grace period on the Healthchecks.io side, or a missed
beat tick never alerts — the pings themselves are already in the code:

| Monitor | Schedule |
| --- | --- |
| hourly refresh (`HOURLY_REFRESH_HEALTHCHECK_URL`) | `5 * * * *` |
| weekly stale timeseries (`WEEKLY_OLD_TIMESERIES_HEALTHCHECK_URL`) | weekly, Mondays ~15:00 UTC |

Grace periods should exceed the task's normal runtime. The hourly refresh fans out to every
stale dataset, so give it room.

## Optional: start using the Sentry traces you already pay for

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

The day-to-day queries live in [observability.md](./observability.md#queries-worth-keeping); these four are just the post-deploy smoke test.

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
# Which datasets are failing, and how. `no_rows` is excluded because it is benign -- see
# the benign/actionable split in observability.md.
sum by (erddap_server, erddap_dataset, outcome) (
  increase(buoybarn_erddap_outcome_total{outcome!~"success|no_rows"}[1h])
) > 0

# Overall failure ratio per server
1 - (
  sum by (erddap_server) (rate(buoybarn_erddap_outcome_total{outcome=~"success|no_rows"}[1h]))
  / sum by (erddap_server) (rate(buoybarn_erddap_outcome_total[1h]))
)

# A failure shape nobody has written a handler for -- worth alerting on
sum by (erddap_dataset) (increase(buoybarn_erddap_outcome_total{outcome="unknown_error"}[6h])) > 0
```

## Disabling

Unset `OTEL_EXPORTER_OTLP_ENDPOINT`. Every metric call becomes a no-op with no exporter
threads and no network traffic; the application behaves exactly as it did before. The
`metrics-exporter` deployment will log that there is nothing to export and exit rather than
crash-looping, so it can be scaled to zero at leisure.
