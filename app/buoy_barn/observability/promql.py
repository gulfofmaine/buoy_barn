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

"""

import json
import logging
import urllib.parse
from functools import cache

from django.conf import settings

logger = logging.getLogger(__name__)


@cache
def _duration_codes() -> frozenset[str]:
    """Codes whose signal is server latency rather than a fetch outcome."""
    from deployments.models import SystemMessage  # noqa: PLC0415

    return frozenset({SystemMessage.Code.BACKOFF_INCREASED.value})


@cache
def _outcome_codes() -> frozenset[str]:
    """Everything else: read off the outcome counter.

    Derived by subtraction rather than listed, so a new `Code` gets a query automatically. The
    listed version silently left the codes added after it was written without one.
    """
    from deployments.models import SystemMessage  # noqa: PLC0415

    return frozenset(code.value for code in SystemMessage.Code) - _duration_codes()


def _escape(value: str) -> str:
    """Escape a value for use inside a PromQL string literal (`"..."`).

    Backslash first, then quote -- escaping the quote first would double-escape the
    backslashes that step just inserted. Without this, a dataset or server name containing a
    `"` could close the label matcher early and inject arbitrary PromQL.
    """
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _build_outcome_query(dataset: str, constraint_group: str) -> str:
    """The outcome-counter query for one dataset, optionally scoped to a constraint group.

    Built on `buoybarn_erddap_outcome_total` even for `end_time_retired`, never on a freshness
    metric: a retirement is invisible to `value_age` by construction, since a retired series
    stops being refreshed and its age flatlines rather than climbing (#1833).

    No `group_left` join to `buoybarn_erddap_constraint_group_info`, though the equivalent
    query in docs/observability.md has one. Two reasons, both found in review: that metric also
    carries `erddap_server` and `timeseries_type`, so a dataset serving two timeseries types
    under one set of constraints gives the match group two right-hand series and the whole
    query errors out; and it is published only for `refreshable()` timeseries, which a
    retirement removes -- so the join would return nothing for the one event it documents. The
    message's own context already carries the constraints the join existed to recover.
    """
    matchers = [f'erddap_dataset="{_escape(dataset)}"']
    if constraint_group:
        matchers.append(f'constraint_group="{_escape(constraint_group)}"')
    selector = "{" + ", ".join(matchers) + "}"
    return (
        "sum by (erddap_dataset, constraint_group, outcome) (\n"
        f"  increase(buoybarn_erddap_outcome_total{selector}[6h])\n"
        ")"
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

        if code_value in _outcome_codes():
            dataset = context.get("dataset")
            if not dataset:
                return None
            return _build_outcome_query(str(dataset), str(context.get("constraint_group") or ""))

        if code_value in _duration_codes():
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

    Needs both `GRAFANA_BASE_URL` and `GRAFANA_PROMETHEUS_UID`; the admin falls back to
    rendering the query as copyable text, so an unset pair degrades rather than breaking.

    Targets Grafana >= 10.2's `panes` Explore scheme.
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
