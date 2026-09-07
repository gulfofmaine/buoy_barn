"""Tests for `buoy_barn.observability.promql`.

`query_for` and `explore_url` both promise to never raise and to never leak a missing value
into a query or URL as the literal string `"None"` -- these tests exercise that contract
directly, alongside the two PromQL shapes the module builds.
"""

import json
import urllib.parse

from django.test import SimpleTestCase, override_settings

from buoy_barn.observability import promql


class TestQueryForOutcomeCodes(SimpleTestCase):
    """Fetch-failure codes, plus the two end_time transitions, use the outcome counter."""

    def test_fetch_failure_code_emits_outcome_counter_dataset_and_group(self):
        query = promql.query_for(
            "not_found",
            {"dataset": "my_dataset", "constraint_group": "abc12345"},
        )

        assert query is not None
        assert "buoybarn_erddap_outcome_total" in query
        assert 'erddap_dataset="my_dataset"' in query
        assert 'constraint_group="abc12345"' in query

    def test_no_constraint_group_omits_the_matcher_but_is_still_valid(self):
        query = promql.query_for("not_found", {"dataset": "my_dataset", "constraint_group": ""})

        assert query is not None
        assert "buoybarn_erddap_outcome_total" in query
        assert 'erddap_dataset="my_dataset"' in query
        assert "constraint_group=" not in query

    def test_missing_constraint_group_key_behaves_like_empty(self):
        query = promql.query_for("not_found", {"dataset": "my_dataset"})

        assert query is not None
        assert "constraint_group=" not in query

    def test_end_time_retired_targets_outcome_counter_not_freshness(self):
        """Issue #1833: a retirement never moves `value_age`, so linking this message to a
        freshness panel would show a reassuring flat line instead of the event itself.
        """
        query = promql.query_for(
            "end_time_retired",
            {"dataset": "my_dataset", "server": "erddap.example.org", "constraint_group": ""},
        )

        assert query is not None
        assert "buoybarn_erddap_outcome_total" in query
        assert "value_age" not in query
        assert "freshness" not in query

    def test_end_time_cleared_uses_outcome_counter_when_context_has_a_dataset(self):
        query = promql.query_for(
            "end_time_cleared",
            {"dataset": "my_dataset", "constraint_group": ""},
        )

        assert query is not None
        assert "buoybarn_erddap_outcome_total" in query


class TestQueryForBackoffIncreased(SimpleTestCase):
    def test_backoff_increased_produces_duration_histogram_query(self):
        query = promql.query_for("backoff_increased", {"server": "erddap.example.org"})

        assert query is not None
        assert "buoybarn_erddap_request_duration_seconds_bucket" in query
        assert 'erddap_server="erddap.example.org"' in query


class TestQueryForMissingOrUnknown(SimpleTestCase):
    def test_unknown_code_returns_none(self):
        assert promql.query_for("some_future_code", {"dataset": "my_dataset"}) is None

    def test_outcome_code_missing_dataset_returns_none(self):
        # This is what `error_handling.py`'s fetch-failure handlers actually record today --
        # `context={"constraints": ..., "error": ...}`, with no dataset name at all.
        query = promql.query_for("not_found", {"constraints": {}, "error": "boom"})

        assert query is None

    def test_backoff_increased_missing_server_returns_none(self):
        assert promql.query_for("backoff_increased", {"constraints": {}}) is None

    def test_no_context_at_all_returns_none_rather_than_raising(self):
        assert promql.query_for("not_found", None) is None
        assert promql.query_for("backoff_increased", {}) is None

    def test_missing_value_never_becomes_the_string_none(self):
        for code, context in [
            ("not_found", {"constraints": {}}),
            ("backoff_increased", {}),
        ]:
            query = promql.query_for(code, context)
            assert query is None or "None" not in query


class TestQueryForEscaping(SimpleTestCase):
    def test_dataset_name_with_quote_is_escaped(self):
        query = promql.query_for("not_found", {"dataset": 'evil"} or 1==1 {"', "constraint_group": ""})

        assert query is not None
        # The literal quote must be escaped, not left free to terminate the string early.
        assert '\\"' in query
        assert 'dataset="evil"}' not in query

    def test_server_name_with_backslash_and_quote_is_escaped(self):
        query = promql.query_for("backoff_increased", {"server": 'weird\\"server'})

        assert query is not None
        assert 'erddap_server="weird\\\\\\"server"' in query


class TestExploreUrl(SimpleTestCase):
    @override_settings(GRAFANA_BASE_URL="", GRAFANA_PROMETHEUS_UID="")
    def test_returns_none_when_grafana_is_unconfigured(self):
        assert promql.explore_url("up") is None

    @override_settings(GRAFANA_BASE_URL="https://grafana.example.org", GRAFANA_PROMETHEUS_UID="")
    def test_returns_none_when_only_base_url_is_set(self):
        assert promql.explore_url("up") is None

    @override_settings(GRAFANA_BASE_URL="", GRAFANA_PROMETHEUS_UID="prometheus")
    def test_returns_none_when_only_uid_is_set(self):
        assert promql.explore_url("up") is None

    @override_settings(
        GRAFANA_BASE_URL="https://grafana.example.org",
        GRAFANA_PROMETHEUS_UID="prometheus-uid",
    )
    def test_url_round_trips_the_exact_query(self):
        query = "sum(rate(buoybarn_erddap_outcome_total[5m]))"

        url = promql.explore_url(query)

        assert url is not None
        assert url.startswith("https://grafana.example.org/explore?")

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        panes = json.loads(params["panes"][0])

        assert panes["a"]["datasource"] == "prometheus-uid"
        assert panes["a"]["queries"][0]["expr"] == query
        assert panes["a"]["queries"][0]["datasource"]["uid"] == "prometheus-uid"

    @override_settings(
        GRAFANA_BASE_URL="https://grafana.example.org/",
        GRAFANA_PROMETHEUS_UID="prometheus-uid",
    )
    def test_trailing_slash_on_base_url_is_not_doubled(self):
        url = promql.explore_url("up")

        assert url is not None
        assert "//explore" not in url.split("://", 1)[1]
        assert url.startswith("https://grafana.example.org/explore?")
