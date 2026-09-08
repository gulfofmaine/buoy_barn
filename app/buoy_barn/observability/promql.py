"""PromQL and Grafana Explore link helpers for :class:`~deployments.models.SystemMessage`.

Turns a message's (code, context) pair into the query for the metric behind it, so an admin
reading "backoff increased" can jump to the signal instead of guessing at label names.

Nothing here raises, and a missing label value yields `None` rather than a matcher holding
the literal string ``"None"``.
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

    Derived by subtraction rather than listed, so a new `Code` gets a query automatically.
    """
    from deployments.models import SystemMessage  # noqa: PLC0415

    return frozenset(code.value for code in SystemMessage.Code) - _duration_codes()


def _escape(value: str) -> str:
    """Escape a value for use inside a PromQL string literal (`"..."`).

    Backslash first, then quote, the other order double-escapes the backslashes the quote
    step inserts. Without this a `"` in a dataset name closes the label matcher early.
    """
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _build_outcome_query(dataset: str, constraint_group: str) -> str:
    """The outcome-counter query for one dataset, optionally scoped to a constraint group.

    On the counter even for `end_time_retired`, never on a freshness metric: a retired series
    stops being refreshed, so its `value_age` flatlines instead of climbing.

    No `group_left` join to `buoybarn_erddap_constraint_group_info`, unlike the equivalent
    query in docs/observability.md. That metric also carries `erddap_server` and
    `timeseries_type`, so two types under one set of constraints error the query out with two
    right-hand series, and it covers only `refreshable()`, which a retirement removes.
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

    `backoff_increased` fires when a server is slow, not when a fetch fails, so latency is
    the signal that moves. The fetch may well have succeeded, only after retrying at length.
    """
    selector = f'{{erddap_server="{_escape(server)}"}}'
    return (
        "histogram_quantile(0.95,\n"
        f"  sum by (le) (rate(buoybarn_erddap_request_duration_seconds_bucket{selector}[30m]))\n"
        ")"
    )


def query_for(code, context) -> str | None:
    """The PromQL that shows this message's own history, or `None` if there isn't one.

    `context` must carry `dataset` (and optionally `constraint_group`) for an outcome-counter
    code, `server` for `backoff_increased`. A message's stored `context` does not always have
    them; see `deployments.admin.system_messages._promql_context`, which fills them in.
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

    Needs both `GRAFANA_BASE_URL` and `GRAFANA_PROMETHEUS_UID`; without them the admin falls
    back to the query as copyable text. Targets Grafana >= 10.2's `panes` Explore scheme.
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
