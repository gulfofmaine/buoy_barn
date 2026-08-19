# Observability

Buoy Barn emits **metrics** over OTLP to an OpenTelemetry collector, and continues to send
**errors and traces** to Sentry. One module is the single place instrumentation is
written, so adding a second destination can be a configuration change.

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

Names below are the OTel instrument names used in the code. Prometheus sees them underscored,
with `_total` on counters and `_seconds` on durations — see
[the naming rules](./observability-deployment.md#metric-names-in-prometheus) before writing
queries.

### ERDDAP upstream health

| Metric | Type | Attributes |
| --- | --- | --- |
| `buoybarn.erddap.outcome` | counter | `erddap.server`, `erddap.dataset`, `constraint_group`, `timeseries.type`, `outcome` |
| `buoybarn.erddap.request.duration` | histogram (s) | `erddap.server`, `outcome` |
| `buoybarn.erddap.request.rows` | histogram | `erddap.server` |
| `buoybarn.erddap.constraint_group.info` | gauge (always 1) | `erddap.server`, `erddap.dataset`, `constraint_group`, `timeseries.type`, `constraints` |

The error handlers return the `outcome` strings directly, so a dataset that has quietly
moved (`not_found`) is distinguishable from one being throttled (`backoff`) or from a server
that has blacklisted us (`forbidden`).

Only two outcomes are benign, and the split is not a judgement call — **it follows the level
the handler logs at.** `handle_500_no_rows_error` is the only handler that logs at `INFO`;
every other one logs at `ERROR`, so it gets an outcome of its own rather than being folded in
with the harmless ones:

| Benign | Actionable |
| --- | --- |
| `success`, `no_rows` | `empty_dataframe`, `not_found`, `forbidden`, `timeout`, `backoff`, `time_range_retired`, `constraint_out_of_range`, `no_matching_time`, `unrecognized_variable`, `unrecognized_constraint`, `server_error`, `unknown_error`, `os_error`, `value_error`, `other` |

`constraint_out_of_range` (a constraint outside a variable's `actual_range`) and
`no_matching_time` (the dataset has no valid time for the request) are both configuration
problems on our side, which is why they are not `no_rows`: an alert on "not benign" must fire
for them. `no_matching_station` is reported as `not_found`, since a missing station and a
missing dataset need the same response.

A dashboard panel that means "is anything actually broken?" is therefore
`outcome!~"success|no_rows"` rather than a list that has to be revised whenever a handler is
added.

`request.rows` is what catches an ERDDAP server answering `200` with an empty body — a
failure that previously showed up only as a log warning with its context commented out.

#### Which constraint group failed

A dataset is fetched **once per `(constraints, timeseries_type)` group** — that is what
`ErddapDataset.group_timeseries_by_constraint_and_type()` returns — so for a dataset carrying
several platforms behind different `stationID=` constraints, one group can fail while its
siblings are perfectly healthy. `constraint_group` is what makes that distinguishable rather
than just "this dataset had a failure".

It is a short hash — the first 8 hex characters of a sha256 over the constraints, serialised
with sorted keys so the same constraints always produce the same id regardless of dict
ordering. A group with no constraints at all, which is most of them, reports `none` rather
than the hash of an empty dict.

The hash is opaque, so **`buoybarn.erddap.constraint_group.info` is the other half**: one
series per (dataset, group), always `1`, carrying the readable constraints as a label. Join it
onto a failure panel to see what actually broke:

```promql
sum by (erddap_dataset, constraint_group) (
  increase(buoybarn_erddap_outcome_total{outcome!~"success|no_rows"}[1h])
) * on (erddap_dataset, constraint_group)
  group_left(constraints) buoybarn_erddap_constraint_group_info
```

It is also logged next to the group on the `Working on timeseries: … (group abc12345)` line,
for when you are already reading logs rather than a dashboard.

#### Cardinality, and one deliberate exception

**`erddap.dataset` and `constraint_group` are on the counter only, never on a histogram.** A
histogram multiplies by its bucket count, so ~384 datasets × 12 outcomes × ~15 buckets would
be tens of thousands of series from a single metric. Latency is tracked per *server*, which is
the unit you act on — you throttle or contact a server, not a dataset.

On the counter, adding the group raises the bound from "dataset × outcome" to
"(dataset, group) × outcome". `timeseries.type` is a property of the group rather than an
independent dimension, so it is not a further multiplier. At two or three groups per dataset
that is roughly 1k (dataset, group) pairs and **~2–3k series in practice**, with a worst case
nearer 12k if every dataset somehow produced every outcome. Only outcomes a group actually
produces ever materialise.

The `constraints` label on the **info metric** is a deliberate exception to the rule that the
constraints JSON must never become a label. That rule exists because the JSON on a hot counter
multiplies with every outcome and every request. On the info metric there is exactly one
series per (dataset, group), it is rewritten once per collection cycle, and the single-replica
exporter is the only process publishing it — so the cost is label *value* length, not series
count. The value is truncated past a couple of hundred characters so a pathological
constraints dict cannot bloat it either.

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

| Metric | Type | Attributes | Which series it counts |
| --- | --- | --- | --- |
| `buoybarn.dataset.refresh_age` | gauge (s) | `erddap.server`, `erddap.dataset` | all datasets — **no active filter** |
| `buoybarn.dataset.never_refreshed` | gauge | `erddap.server` | all datasets — **no active filter** |
| `buoybarn.timeseries.value_age` | gauge (s) | `platform`, `erddap.server`, `timeseries.type`, `agg` | filtered to `active=True`, not retired, populated |
| `buoybarn.timeseries.count` | gauge | `erddap.server`, `state` | all series, **split** by state |

`value_age` is aggregated per *platform*, with `agg=min` for the freshest reading and
`agg=max` for the oldest — `agg=min` is the one that answers "is this buoy reporting?".
Per-series detail stays in the admin, because there are thousands of timeseries and they
churn as series are retired.

### How `active` and retired series are treated

Not uniformly, so it is worth being explicit — the rightmost column above is the short version.

- **`value_age` filters.** Only `active=True` series with `end_time IS NULL` and a non-null
  `value_time` are included. So a retired or deactivated series can never drag the gauge into
  looking stale — but it is also invisible here, which is the point: this metric answers "is
  the data we are still trying to collect arriving?".
- **`timeseries.count` splits** rather than filters, by `state` ∈ `active` / `inactive` /
  `retired` / `never_populated`. This is where retired and deactivated series are visible, and
  its `active` definition is the same predicate `value_age` uses, so the two agree by
  construction. `never_populated` (a series that has never had a `value_time`) is usually a
  configuration mistake rather than an outage.
- **`refresh_age` and `never_refreshed` are dataset-level and have no notion of `active` at
  all.** This is a trap worth knowing: **a dataset whose every timeseries has been retired
  still reports a perfectly healthy refresh age**, because the refresh task still runs, still
  stamps `refresh_attempted`, and simply finds nothing to fetch. A low `refresh_age` is
  therefore evidence that refreshes are *happening*, not that data is *arriving* — pair it
  with `timeseries.count{state="active"}` for that dataset's server before concluding
  anything.

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

## Queries worth keeping

Ready to paste into Grafana Explore or a dashboard panel. Note the names below are the
Prometheus-side names, which differ from the instrument names above — see
[the naming rules](./observability-deployment.md#metric-names-in-prometheus).

**Which constraint group is failing, with its real constraints** — the join that makes the
opaque `constraint_group` hash useful:

```promql
sum by (erddap_server, erddap_dataset, constraint_group, outcome) (
  increase(buoybarn_erddap_outcome_total{outcome!~"success|no_rows"}[1h])
) * on (erddap_dataset, constraint_group)
  group_left(constraints) buoybarn_erddap_constraint_group_info
```

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

Metrics from `web` and `celery-worker` should appear. Seeing the worker's is the
important check — the OTel SDK is not fork-safe, and getting the prefork initialisation
wrong fails silently rather than loudly. See the extended comment in `bootstrap.py`.

To confirm the failure path is visible, point a dataset at a broken ERDDAP URL and refresh
it: `buoybarn.erddap.outcome` should record a non-`success` outcome while the Celery task
still reports success.

## Health checks

`/ht/` is unchanged, and still what the Kubernetes liveness and startup probes use.

Two things worth knowing:

- **`/ht/?format=openmetrics` already renders health checks in Prometheus/OpenMetrics
  format** (`django_health_check_*`), for free, in the installed django-health-check 4.5.
  Nothing scrapes it today. Wiring up a ServiceMonitor for it is tracked in
  [#1844](https://github.com/gulfofmaine/buoy_barn/issues/1844) — it needs a Prometheus
  Operator selector label that belongs with the observability stack rather than here, so it is
  a scrape-config change rather than an app change.
- **The commented-out Celery ping check was left commented out deliberately.** See the note
  in `settings.py`; enabling it as written would break, and enabling it correctly would tie
  web-pod liveness to worker responsiveness within one second.
