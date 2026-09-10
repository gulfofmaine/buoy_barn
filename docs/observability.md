# Observability

Buoy Barn emits **metrics** over OTLP to an OpenTelemetry collector, and continues to send
**errors and traces** to Sentry. One module is the single place instrumentation is
written, so adding a second destination can be a configuration change.

For the deployment steps, see [observability-deployment.md](./observability-deployment.md).

## Why metrics, given Sentry was already there

Sentry could not answer the three questions that matter most here:

1. Which ERDDAP servers and datasets are failing? - The refresh pipeline swallows almost
   every ERDDAP error, `handle_http_errors` returns for every branch it recognises,
   `OSError` logs and returns, an empty response is a warning. So Celery reports ~100% task
   success even when every fetch fails, and a task-level failure counter would read zero.
2. How long does anything take? - Before this there was no timing instrumentation
   anywhere in the codebase, so nobody knew whether an ERDDAP call took 2s or 50s, or how
   close `refresh_dataset` ran to its 1800s hard limit.
3. How stale is the data? - Only visible by eye in the admin's coloured refresh column,
   or in a Slack digest that is only scheduled when Slack env vars are set.

## Can the same instrumentation feed both Sentry and Prometheus?

| Signal | Prometheus | Sentry |
| --- | --- | --- |
| Metrics | native target | **not ingestible over OTLP** |
| Traces / spans | derivable in the collector (`spanmetrics`) | ingests OTLP traces |
| Errors | only as a counter | native target |

Sentry's metrics beta was retired in October 2024. Its replacement, Application Metrics
(`sentry_sdk.metrics.count / gauge / distribution`), is a *separate call* from the OTel
meter rather than another exporter, and is billed like logs. So:

- Metrics - go to OTel only.
- Errors and traces - stay with Sentry, via the `CeleryIntegration` and `DjangoIntegration`
  that were already configured. Note `SENTRY_TRACES_SAMPLE_RATE` defaults to `0`, so that
  span data is currently discarded, set it to something non-zero to start using it.
- A small allow-list of failure counters can be mirrored into Sentry Application Metrics by
  setting `BUOY_BARN_SENTRY_METRIC_MIRROR=true`. Off by default: span attributes already
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

The layer switches itself off when
`DJANGO_ENV=test`, the same way Sentry disables itself.

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
| `success`, `no_rows` | `empty_dataframe`, `not_found`, `forbidden`, `timeout`, `backoff`, `time_range_retired`, `time_range_reported`, `constraint_out_of_range`, `no_matching_time`, `unrecognized_variable`, `unrecognized_constraint`, `server_error`, `unknown_error`, `os_error`, `value_error`, `other` |

`constraint_out_of_range` (a constraint outside a variable's `actual_range`) and
`no_matching_time` (the dataset has no valid time for the request) are both configuration
problems on our side, which is why they are not `no_rows`: an alert on "not benign" must fire
for them. `no_matching_station` is reported as `not_found`, since a missing station and a
missing dataset need the same response.

A dashboard panel that means "is anything actually broken?" is therefore
`outcome!~"success|no_rows"` rather than a list that has to be revised whenever a handler is
added.

Both sets are declared as `OUTCOMES` and `BENIGN_OUTCOMES` in
`deployments/tasks/error_handling.py` — with the handlers that produce them, not with the
metrics facade that records them. The facade reads them from there, and a test scans the
handlers for returned outcome strings so that one which is never declared fails the build
rather than quietly recording as `other`.

`request.rows` is what catches an ERDDAP server answering `200` with an empty body — a
failure that previously showed up only as a log warning with its context commented out.

#### Which constraint group failed

A dataset is fetched once per `(constraints, timeseries_type)` group, that is what
`ErddapDataset.group_timeseries_by_constraint_and_type()` returns, so for a dataset carrying
several platforms behind different `stationID=` constraints, one group can fail while its
siblings are perfectly healthy. `constraint_group` is what makes that distinguishable rather
than just "this dataset had a failure".

It is a short hash — the first 8 hex characters of a sha256 over the constraints, serialised
with sorted keys so the same constraints always produce the same id regardless of dict
ordering. A group with no constraints at all, which is most of them, reports `none` rather
than the hash of an empty dict.

The hash is opaque, so `buoybarn.erddap.constraint_group.info` is what makes it
interpretable: one series per (dataset, group), always `1`, carrying the readable constraints
as a label. Join it onto a failure panel to see what actually broke:

```promql
sum by (erddap_dataset, constraint_group) (
  increase(buoybarn_erddap_outcome_total{outcome!~"success|no_rows"}[1h])
) * on (erddap_dataset, constraint_group)
  group_left(constraints) buoybarn_erddap_constraint_group_info
```

It is also logged next to the group on the `Working on timeseries: … (group abc12345)` line,
for when you are already reading logs rather than a dashboard. It is additionally set as the
`erddap-constraint-group` tag on Sentry errors raised from that fetch.

#### Cardinality, and one deliberate exception

`erddap.dataset` and `constraint_group` are on the counter only, never on a histogram. A
histogram multiplies by its bucket count, so ~384 datasets × 12 outcomes × ~15 buckets would
be tens of thousands of series from a single metric. Latency is tracked per server, which is
the unit you act on, you throttle or contact a server, not a dataset.

On the counter, adding the group raises the bound from "dataset × outcome" to
"(dataset, group) × outcome". `timeseries.type` is a property of the group rather than an
independent dimension, so it is not a further multiplier. At two or three groups per dataset
that is roughly 1k (dataset, group) pairs and ~2–3k series in practice, with a worst case
nearer 12k if every dataset somehow produced every outcome. Only outcomes a group actually
produces ever materialise.

The `constraints` label on the info metric is a deliberate exception to the rule that the
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

- `value_age` filters. Only `active=True` series with `end_time IS NULL` and a non-null
  `value_time` are included. So a retired or deactivated series can never drag the gauge into
  looking stale — but it is also invisible here, which is the point: this metric answers "is
  the data we are still trying to collect arriving?".
- `timeseries.count` splits rather than filters, by `state` ∈ `active` / `inactive` /
  `retired` / `never_populated`. This is where retired and deactivated series are visible, and
  its `active` definition is the same predicate `value_age` uses, so the two agree by
  construction. `never_populated` (a series that has never had a `value_time`) is usually a
  configuration mistake rather than an outage.
- `refresh_age` and `never_refreshed` are dataset-level and have no notion of `active` at
  all. A dataset whose every timeseries has been retired
  still reports a perfectly healthy refresh age, because the refresh task still runs, still
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

## Admin system messages

The refresh pipeline above acts on its own and swallows almost every error it meets — that
is the whole reason the outcome counter exists. The most consequential of those self-directed
actions is `TimeSeries.end_time`: `handle_500_time_range_error` writes it when ERDDAP reports
that a dataset's data ends before the requested range, and a set `end_time` retires that
series from every future refresh and from Mariners Dashboard (issue #1855) without telling
anyone. Metrics made that failure mode visible on a dashboard; `SystemMessage` makes it
visible to the admin who can decide whether the retirement is correct and undo it if not.

A `SystemMessage` is a small, machine-written row — level, code, a human-readable
explanation, and a foreign key to whatever subject it concerns — surfaced as a sidebar on the
Platform, Dataset, Server and Timeseries change pages (`SystemMessageSidebarMixin`), and in
its own `SystemMessageAdmin` listing. The subject is one of four nullable foreign keys
(`platform`, `timeseries`, `dataset`, `server`) with a check constraint asserting exactly one
is set, rather than a generic foreign key: the number of platforms, datasets, servers and
timeseries keeps growing, but the set of models does not, and real columns are what let the
changelist's reach lookups use an index.

`SUBJECT_KINDS` in `deployments/admin/system_messages.py` is the single description of how a
message reaches a page — the sidebar, the changelist filter and the severity sort all read
it, so a page cannot offer a filter that hides rows whose own badge says they have a message.
Each path is queried on its own rather than OR'd into one lookup, because Postgres plans an
OR across four multi-valued paths as a single many-way left join with an OR'd join filter,
which no index can serve.

### What gets recorded, and at what level

| Outcome | Code | Level | Subject |
| --- | --- | --- | --- |
| `forbidden` | `forbidden` | `danger` | Dataset |
| `not_found` | `not_found` | `danger` | Dataset |
| `unrecognized_variable` | `unrecognized_variable` | `warning` | Dataset |
| `unrecognized_constraint` | `unrecognized_constraint` | `warning` | Dataset |
| `server_error` | `server_error` | `warning` | Dataset |
| `unknown_error` | `unknown_error` | `warning` | Dataset |
| `constraint_out_of_range` | `constraint_out_of_range` | `warning` | Dataset |
| `no_matching_time` | `no_matching_time` | `warning` | Dataset |
| `time_range_reported` | `time_range_reported` | `info` | Dataset |
| `time_range_retired` | `end_time_retired` | `danger` | Timeseries |
| `time_range_inconsistent` | `time_range_inconsistent` | `warning` | Timeseries |
| *(a later fetch supersedes a retirement)* | `end_time_cleared` | `info` | Timeseries |
| *(per-run backoff in `refresh_dataset`, not a fetch outcome)* | `backoff_increased` | `warning` | Dataset |

The first nine rows are `FETCH_FAILURE_MESSAGES` in `deployments/tasks/outcomes.py`, which
owns the whole vocabulary — the enum, the benign set, and this map. They were split across
two modules until the halves drifted and two outcomes ended up recording nothing. A test now
asserts the map is exhaustive: every non-benign `Outcome` is either a key here or named in
`HANDLED_ELSEWHERE` with the reason it is recorded some other way.

Only outcomes outside `BENIGN_OUTCOMES` get an entry (see
[the benign/actionable table above](#erddap-upstream-health)): the level a handler logs at
says whether its condition is benign, and `handle_500_no_rows_error` is the only one at
`INFO`.

`time_range_retired` is in `HANDLED_ELSEWHERE`, not because it is benign but because
`handle_500_time_range_error` records it per affected timeseries as `end_time_retired`, which
names the platform that stopped refreshing rather than saying something is wrong with the
dataset. `time_range_reported` is the same handler's other outcome: ERDDAP reported a range
ending inside the last week, recent enough that nothing was retired. Nothing
timeseries-specific happened, so that one is a dataset-level row.

`time_range_inconsistent` is the same handler's third outcome, also in `HANDLED_ELSEWHERE` and
also recorded per-timeseries (as `time_range_inconsistent`, `warning`): a series whose
`value_time` is already after the range end ERDDAP just reported is left untouched instead of
retired.`series.value_time > series.end_time` should not happen for real data, so the 500 is
treated as more likely wrong or transient than the series actually being dead (issue #1855).
The handler still returns `time_range_retired` if any series in the group was retired; it only
returns `time_range_inconsistent` when every series was guarded off.

### Deduplication

Every message is upserted on the `(subject, code, constraint_group)` key `SystemMessage`
enforces, in `record_system_message`. That key is four partial unique constraints, one per
subject column, each conditioned on that column being non-null — Postgres treats NULLs as
distinct, so a single unique constraint over all four subject columns (three of which are
always NULL) would never fire. A recurring problem
bumps `occurrences` and `last_seen` on the row that is already there instead of creating a
new one — the equivalent Sentry issue for one of these failure shapes carries roughly 17,000
events in 90 days, and a table with one row per event would be as unreadable as the logs this
feature exists to replace.

### Acknowledgement is global, and contained

Acknowledging a message is global, not per user: there is no per-viewer dismissal list, just
`acknowledged_at` and `acknowledged_by` on the row itself. It is also not permanent —
`SystemMessageQuerySet.outstanding()` treats a message as outstanding again once it recurs
*after* being acknowledged (`last_seen` moves past `acknowledged_at`), so dismissing one
occurrence cannot hide the next.

Because acknowledging is global, a page may only offer the inline Acknowledge button when
everything the message reaches is contained within that page — otherwise a click on one
platform's page would silently dismiss a problem three other platforms still have.
`admin.py`'s `compute_message_reach` resolves that reach through `TimeSeries`, the only model
that joins platforms, datasets and servers together, and containment is judged along the axis
the current page measures: a Platform page requires every platform reached to be this
platform, a Dataset page requires every dataset reached to be this dataset, and so on.
Concretely: a message attached to a dataset stops being dismissable inline from a platform
page as soon as a *second* platform has a timeseries on that dataset — at that point
acknowledging has to happen from the `SystemMessageAdmin` listing (or the dataset's own page)
instead, where the "Impact" field spells out everything the click would dismiss.

### Resolution

Recognised outcomes resolve stale failures for that dataset and constraint group: `update_values_for_timeseries` calls `_resolve_stale_fetch_failures`, which
resolves every fetch-failure code except the one just recorded. A dataset that switches
failure mode (say, `forbidden` to `not_found`) closes out the old message instead of leaving
it outstanding forever. On `Outcome.SUCCESS` or `Outcome.EMPTY_DATAFRAME` there is nothing to
keep, so every fetch-failure code is resolved.

`backoff_increased` is recorded outside
the map, but no longer warranted once a fetch for that group succeeds.

Clearing an
`end_time` resolves the retirement that set it (`resolve_system_messages(series,
SystemMessage.Code.END_TIME_RETIRED)`).

### The PromQL each message carries

`buoy_barn/observability/promql.py`'s `query_for(code, context)` turns a message's `(code,
context)` back into the query behind it, ready to paste into Grafana or copy from the admin.
Every code resolves to a `buoybarn_erddap_outcome_total` query scoped to the message's dataset
— and constraint group, when it has one — over a 6h window, except `backoff_increased`, which
resolves to the request-duration histogram for the server: a slow server is a latency problem,
and the outcome counter has nothing to say about it.

Two traps, both found in review.

**`end_time_retired` links to the outcome counter and deliberately not to
`buoybarn_timeseries_value_age_seconds`.** `value_age` only covers active, non-retired series,
so once a series is retired its age stops updating rather than climbing. A freshness panel
linked from an `end_time_retired` message would show a reassuring flat line for the one
failure mode with confirmed data loss (issue #1833).

**These queries do not join `buoybarn_erddap_constraint_group_info`, though the
constraint-group query [further down](#queries-worth-keeping) does.** That metric also carries
`erddap_server` and `timeseries_type`, so a dataset serving two timeseries types under one set
of constraints gives the match group two right-hand series and PromQL errors the query out.
And it is published only for `refreshable()` timeseries — which a retirement removes — so for
`end_time_retired` the join would return nothing for the event it documents. The join existed
to recover the constraints behind the opaque group hash, and the message's own `context`
already carries them.

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
  in `urls.py`; enabling it as written would break, and enabling it correctly would tie
  web-pod liveness to worker responsiveness within one second.
- **`/ht/celery/` is a separate endpoint that runs only the Celery `Ping` check**, with its
  timeout raised from the library's 1-second default to 10 seconds so a busy worker doesn't
  read as a dead one. It must never back a probe that restarts anything: `Ping`'s
  `check_active_queues` step makes a second round trip through `self.app.control.inspect(...)`
  that ignores our timeout entirely and always uses Celery's own hardcoded 1-second default,
  so this endpoint can still fail on a worker that is merely busy.
- **The worker, beat and flower deployments each carry their own `livenessProbe`** now (see
  `k8s/base/celery-worker.yaml`, `celery-beat.yaml`, `celery-flower.yaml`), which is the actual
  fix for the incident that motivated this section: a dead Redis connection used to leave
  worker and beat running but silently doing nothing.
  - **worker and beat** exec `celery inspect ping` inside the container (wrapped in `sh -c`
    so `$HOSTNAME` gets shell-expanded, since exec probes don't go through a shell or get
    Kubernetes' `$(VAR)` substitution). The ping traverses the broker, so it catches exactly
    the incident's failure mode. `timeoutSeconds` is 20, comfortably above the ~7s it took to
    fail against an unreachable broker in testing. beat has no pidbox of its own to address
    (no `-d` flag), so it can't tell "no worker replied" apart from "broker unreachable" --
    either way it retries and eventually restarts, which is an acceptable false-positive-ish
    restart because beat carries no long-running state.
  - **flower** gets a plain HTTP probe against its own `/healthcheck` endpoint.
