"""PromQL and Grafana Explore link helpers for :class:`~deployments.models.SystemMessage`.

Every `SystemMessage` already carries a human-readable explanation; this module turns that
same (code, context) pair into the PromQL query that shows the metric behind it, so an admin
reading "backoff increased" or "end time retired" can jump straight to the signal instead of
guessing at label names.

Design rules mirror :mod:`buoy_barn.observability.metrics`, since both sit on the same
never-raise contract:

1. Never raise. A malformed or unexpected `context` must degrade to `None`, not a traceback
   in the admin.
2. No query is better than a wrong one. A dataset name or label value that is simply missing
   from `context` means `None`, not a query with the literal string ``"None"`` baked into a
   label matcher.

`code` is accepted as a plain string rather than by importing
:class:`deployments.models.SystemMessage.Code` -- this module has no reason to depend on the
app registry, and the values below are exactly the ``Code`` choices' string values.
"""

import json
import logging
import urllib.parse

from django.conf import settings

logger = logging.getLogger(__name__)

#: Codes whose own history is best read off `buoybarn.erddap.outcome` -- the counter behind
#: every fetch-failure branch in `error_handling.py`, plus the two end_time transitions
#: `refresh.py` records when a timeseries stops or resumes being refreshed.
#:
#: `end_time_retired` belongs here and NOT with any freshness metric -- see the comment on
#: `_build_outcome_query` for why that particular substitution is a trap rather than a
#: simplification.
_OUTCOME_CODES = frozenset(
    {
        "end_time_retired",
        "end_time_cleared",
        "not_found",
        "forbidden",
        "unrecognized_variable",
        "unrecognized_constraint",
        "server_error",
        "unknown_error",
    },
)

#: `backoff_increased` describes a slow server, not a failed fetch, so its signal is latency
#: rather than outcome -- see `_build_duration_query`.
_DURATION_CODES = frozenset({"backoff_increased"})


def _escape(value: str) -> str:
    """Escape a value for use inside a PromQL string literal (`"..."`).

    Backslash first, then quote -- escaping the quote first would double-escape the
    backslashes that step just inserted. Without this, a dataset or server name containing a
    `"` could close the label matcher early and inject arbitrary PromQL.
    """
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _build_outcome_query(dataset: str, constraint_group: str) -> str:
    """The outcome-counter query for one dataset, optionally scoped to a constraint group.

    Joined to `buoybarn_erddap_constraint_group_info` exactly as `docs/observability.md`
    does, so the opaque `constraint_group` hash resolves to its real constraints in the same
    query rather than requiring a second lookup.

    Deliberately built on `buoybarn_erddap_outcome_total` even for `end_time_retired`, never
    on `buoybarn_timeseries_value_age_seconds` or any other freshness metric. Issue #1833:
    a retirement is invisible to `value_age` *by construction* -- `value_age` only covers
    active, non-retired series (see docs/observability.md), so once a series is retired its
    age simply stops updating rather than climbing. Linking a retirement message to a
    freshness panel would show a reassuring flat line for the exact event the message is
    warning about.
    """
    matchers = [f'erddap_dataset="{_escape(dataset)}"']
    if constraint_group:
        matchers.append(f'constraint_group="{_escape(constraint_group)}"')
    selector = "{" + ", ".join(matchers) + "}"
    return (
        "sum by (erddap_dataset, constraint_group, outcome) (\n"
        f"  increase(buoybarn_erddap_outcome_total{selector}[6h])\n"
        ") * on (erddap_dataset, constraint_group)\n"
        "  group_left(constraints) buoybarn_erddap_constraint_group_info"
    )


def _build_duration_query(server: str) -> str:
    """The request-duration histogram for one server.

    `backoff_increased` fires when a server is slow enough to trigger backoff, not when a
    fetch fails -- the outcome counter has nothing to say about that, since the fetch may
    well have "succeeded" only after retrying at length. Latency, not outcome, is the signal
    that actually moves.
    """
    selector = f'{{erddap_server="{_escape(server)}"}}'
    return (
        "histogram_quantile(0.95,\n"
        f"  sum by (le) (rate(buoybarn_erddap_request_duration_seconds_bucket{selector}[30m]))\n"
        ")"
    )


def query_for(code, context) -> str | None:
    """The PromQL that shows this message's own history, or `None` if there isn't one.

    `context` is expected to carry whatever labels the query needs -- `dataset` (and
    optionally `constraint_group`) for an outcome-counter code, `server` for
    `backoff_increased`. A `SystemMessage`'s own `context` field does not always include
    these (the fetch-failure handlers in `error_handling.py` record only `constraints` and
    `error`, for instance), so a caller assembling `context` from a message may need to add
    them from the message's subject or `constraint_group` field. Whatever the reason a
    required key is missing, the result is `None` -- never a query with `"None"` standing in
    for a label value.
    """
    try:
        code_value = str(code)
        context = context or {}

        if code_value in _OUTCOME_CODES:
            dataset = context.get("dataset")
            if not dataset:
                return None
            return _build_outcome_query(str(dataset), str(context.get("constraint_group") or ""))

        if code_value in _DURATION_CODES:
            server = context.get("server")
            if not server:
                return None
            return _build_duration_query(str(server))
    except Exception:
        logger.debug("Could not build a PromQL query for %r", code, exc_info=True)
        return None
    else:
        return None


def explore_url(query) -> str | None:
    """Grafana Explore deep link for `query`, or `None` when Grafana isn't configured.

    `None` is the normal case today -- Grafana is not deployed for this project, and nothing
    downstream may assume this ever returns a URL. Both `GRAFANA_BASE_URL` and
    `GRAFANA_PROMETHEUS_UID` must be set, since a datasource UID is required to build a
    working link at all.

    Targets Grafana >= 10.2's `panes`-based Explore URL scheme (a single JSON blob covering
    every pane). Older Grafana instead read a single pane from a `?left=` query parameter
    with a similar-but-not-identical JSON shape -- all of that URL-shape knowledge is kept in
    this one function so supporting an older Grafana is a one-line change here, not a change
    at every call site.

    Never raises, matching the rest of this package's contract: a malformed setting or a
    query that fails to serialise must not break whatever page is rendering the message.
    """
    try:
        base_url = settings.GRAFANA_BASE_URL
        uid = settings.GRAFANA_PROMETHEUS_UID
        if not base_url or not uid:
            return None

        panes = {
            "a": {
                "datasource": uid,
                "queries": [
                    {
                        "refId": "A",
                        "expr": query,
                        "datasource": {"type": "prometheus", "uid": uid},
                    },
                ],
                "range": {"from": "now-24h", "to": "now"},
            },
        }
        encoded_panes = urllib.parse.quote(json.dumps(panes))
    except Exception:
        logger.debug("Could not build a Grafana Explore URL", exc_info=True)
        return None
    else:
        return f"{base_url.rstrip('/')}/explore?schemaVersion=1&orgId=1&panes={encoded_panes}"
