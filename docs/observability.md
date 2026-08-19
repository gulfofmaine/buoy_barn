# Observability

Buoy Barn emits **metrics** over OTLP to an OpenTelemetry collector, and continues to send
**errors and traces** to Sentry. One facade module is the single place instrumentation is
written, so adding a second destination is a configuration change rather than a rewrite.

For the deployment steps, see [observability-deployment.md](./observability-deployment.md).

## Why metrics, given Sentry was already there

Sentry could not answer the three questions that matter most here:

1. **Which ERDDAP servers and datasets are failing?** The refresh pipeline swallows almost
   every ERDDAP error — `handle_http_errors` returns for every branch it recognises,
   `OSError` logs and returns, an empty response is a warning. So Celery reports ~100% task
   success even when every fetch fails, and a task-level failure counter would read zero.
2. **How long does anything take?** Before this there was no timing instrumentation
   anywhere in the codebase, so nobody knew whether an ERDDAP call took 2s or 50s, or how
   close `refresh_dataset` ran to its 1800s hard limit.
3. **How stale is the data?** Only visible by eye in the admin's coloured refresh column,
   or in a Slack digest that is only scheduled when Slack env vars are set.

## Can the same instrumentation feed both Sentry and Prometheus?

Partly, and the split is worth knowing:

| Signal | Prometheus | Sentry |
| --- | --- | --- |
| Metrics | native target | **not ingestible over OTLP** |
| Traces / spans | derivable in the collector (`spanmetrics`) | ingests OTLP traces |
| Errors | only as a counter | native target |

Sentry's metrics beta was retired in October 2024. Its replacement, Application Metrics
(`sentry_sdk.metrics.count / gauge / distribution`), is a *separate call* from the OTel
meter rather than another exporter, and is billed like logs. So:

- **Metrics** go to OTel only.
- **Errors and traces** stay with Sentry, via the `CeleryIntegration` and `DjangoIntegration`
  that were already configured. Note `SENTRY_TRACES_SAMPLE_RATE` defaults to `0`, so that
  span data is currently discarded — set it to something non-zero to start using it.
- A small allow-list of failure counters can be mirrored into Sentry Application Metrics by
  setting `BUOY_BARN_SENTRY_METRIC_MIRROR=true`. **Off by default**: span attributes already
  cover most of what it would buy, and it costs money.

Adopting OTel *tracing* as well (via `OTLPIntegration` plus the
`opentelemetry-instrumentation-*` packages) is a clean follow-on and needs no rework of what
is here. It was left out deliberately: the Sentry integrations already create spans for
every request and task, and running both would double-instrument.

## Configuration

`buoy_barn/observability/bootstrap.py`'s module docstring is the authoritative list of
environment variables, kept next to the code that reads them. The short version:

| Variable | Effect |
| --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | The collector. **Unset means the entire layer is a no-op.** |
| `OTEL_SERVICE_NAME` | Defaults to `buoy-barn`. |
| `BUOY_BARN_OTEL_ROLE` | `web` / `worker` / `beat` / `flower` / `mqtt` / `exporter`. Guessed from the command line if unset. |
| `BUOY_BARN_SENTRY_METRIC_MIRROR` | Mirror failure counters into Sentry. Off by default. |
| `WEEKLY_OLD_TIMESERIES_HEALTHCHECK_URL` | Healthchecks.io monitor for the weekly stale-timeseries task. |

Nothing needs to be disabled for tests: the layer switches itself off when
`DJANGO_ENV=test`, the same way Sentry does.

## What is exported

### ERDDAP upstream health

| Metric | Type | Attributes |
| --- | --- | --- |
| `buoybarn.erddap.outcome` | counter | `erddap.server`, `erddap.dataset`, `outcome` |
| `buoybarn.erddap.request.duration` | histogram (s) | `erddap.server`, `outcome` |
| `buoybarn.erddap.request.rows` | histogram | `erddap.server` |

`outcome` is one of `success`, `no_rows`, `empty_dataframe`, `not_found`, `forbidden`,
`timeout`, `backoff`, `time_range_retired`, `unrecognized_variable`,
`unrecognized_constraint`, `server_error`, `unknown_error`, `os_error`, `value_error`, or
`other`. The error handlers return these strings directly, so a dataset that has quietly
moved (`not_found`) is distinguishable from one being throttled (`backoff`) or from a server
that has blacklisted us (`forbidden`).

`request.rows` is what catches an ERDDAP server answering `200` with an empty body — a
failure that previously showed up only as a log warning with its context commented out.

**`erddap.dataset` is on the counter only, never on a histogram.** With ~384 datasets, a
histogram labelled by dataset would produce tens of thousands of series; latency is tracked
per *server*, which is the unit you act on.

### Celery task health

| Metric | Type | Attributes |
| --- | --- | --- |
| `buoybarn.celery.task.count` | counter | `celery.task`, `celery.state` |
| `buoybarn.celery.task.duration` | histogram (s) | `celery.task`, `celery.state` |
| `buoybarn.celery.task.in_progress` | up/down counter | `celery.task` |
| `buoybarn.celery.task.queue_latency` | histogram (s) | `celery.task` |
| `buoybarn.celery.queue.depth` | gauge | `celery.queue` |

All of it comes from Celery signals, so new tasks are measured automatically with no
per-task code. `duration` answers "how close is `refresh_server` to the 1800s hard limit",
`in_progress` reveals genuinely stuck tasks, and `queue_latency` is the backlog signal.

### Data freshness

| Metric | Type | Attributes |
| --- | --- | --- |
| `buoybarn.dataset.refresh_age` | gauge (s) | `erddap.server`, `erddap.dataset` |
| `buoybarn.dataset.never_refreshed` | gauge | `erddap.server` |
| `buoybarn.timeseries.value_age` | gauge (s) | `platform`, `erddap.server`, `timeseries.type`, `agg` |
| `buoybarn.timeseries.count` | gauge | `erddap.server`, `state` |

`value_age` is aggregated per *platform*, with `agg=min` for the freshest reading and
`agg=max` for the oldest — `agg=min` is the one that answers "is this buoy reporting?".
Per-series detail stays in the admin, because there are thousands of timeseries and they
churn as series are retired.

### Everything else

| Metric | Type | Attributes |
| --- | --- | --- |
| `buoybarn.log.records` | counter | `logger`, `level` |
| `buoybarn.healthcheck.ping` | counter | `monitor`, `outcome` |

`log.records` counts warnings and errors by logger. It is the backstop for the swallowed
errors: it needs no call-site changes and cannot disturb the log text the test suite asserts
on. `healthcheck.ping` exists because every Healthchecks.io ping site swallows
`requests.RequestException`, so a monitor that silently stops being pinged used to look
exactly like a healthy one.

## Beat and schedule monitoring

"Did beat actually tick?" is answered by **Healthchecks.io**, not by a metric — a metric
that stops being emitted is indistinguishable from a failed scrape, whereas a monitor alerts
precisely on absence.

- `hourly_default_dataset_refresh` pings `HOURLY_REFRESH_HEALTHCHECK_URL`.
- `more_thank_a_week_old` pings `WEEKLY_OLD_TIMESERIES_HEALTHCHECK_URL` (new; it previously
  had no monitor at all). It pings on completion even when nothing is stale, so a quiet week
  is not mistaken for a failure.

**Both monitors need a cron schedule and grace period configured on the Healthchecks.io side
or a missed tick never alerts.** That step is easy to skip and makes the whole thing a no-op.

## Working on this locally

`docker compose up` starts an `otel-collector` service that logs everything it receives:

```bash
make up
docker compose logs -f otel-collector
```

Metrics from **both** `web` and `celery-worker` should appear. Seeing the worker's is the
important check — the OTel SDK is not fork-safe, and getting the prefork initialisation
wrong fails silently rather than loudly. See the extended comment in `bootstrap.py`.

To confirm the failure path is visible, point a dataset at a broken ERDDAP URL and refresh
it: `buoybarn.erddap.outcome` should record a non-`success` outcome while the Celery task
still reports success. That gap is the entire reason this layer exists.

## Health checks

`/ht/` is unchanged, and still what the Kubernetes liveness and startup probes use.

Two things worth knowing:

- **`/ht/?format=openmetrics` already renders health checks in Prometheus/OpenMetrics
  format** (`django_health_check_*`), for free, in the installed django-health-check 4.5.
  Nothing scrapes it today; it is a cheap addition if you want check status in Prometheus
  alongside these metrics.
- **The commented-out Celery ping check was left commented out deliberately.** See the note
  in `settings.py`; enabling it as written would break, and enabling it correctly would tie
  web-pod liveness to worker responsiveness within one second.
