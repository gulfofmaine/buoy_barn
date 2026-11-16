"""Tests for fetching dataframes from ERDDAP."""

from types import SimpleNamespace
from unittest.mock import patch

import httpx2
import pytest
from erddapy import ERDDAP

from buoy_barn.http import ERDDAPHTTPError
from deployments.utils.erddap_datasets import retrieve_dataframe

CSVP = "time (UTC),temp (C)\n2024-01-01T00:00:00Z,1.5\n2023-01-01T00:00:00Z,2.5\n"


def _server(timeout: int):
    e = ERDDAP(server="https://erddap.example/erddap", protocol="tabledap")
    e.dataset_id = "test_dataset"
    e.variables = ["time", "temp"]
    return SimpleNamespace(request_timeout_seconds=timeout, connection=lambda: e), e


def _response(status: int, text: str) -> httpx2.Response:
    return httpx2.Response(
        status,
        text=text,
        request=httpx2.Request(
            "GET",
            "https://erddap.example/erddap/tabledap/test_dataset.csvp",
        ),
    )


def test_retrieve_dataframe_passes_server_timeout_and_sorts():
    server, e = _server(timeout=17)
    with (
        patch("deployments.utils.erddap_datasets.setup_variables", return_value=e),
        patch("buoy_barn.http.get", return_value=_response(200, CSVP)) as get,
    ):
        df = retrieve_dataframe(server, "test_dataset", {}, [])

    assert get.call_args.kwargs["timeout"] == 17
    assert get.call_args.args[0] == e.get_download_url(response="csvp")
    assert list(df["temp (C)"]) == [2.5, 1.5], "sorted by time"
    assert str(df["time (UTC)"].iloc[0]).startswith("2023"), "time column is parsed"


def test_retrieve_dataframe_raises_erddap_error_with_body():
    server, e = _server(timeout=17)
    with (
        patch("deployments.utils.erddap_datasets.setup_variables", return_value=e),
        patch(
            "buoy_barn.http.get",
            return_value=_response(404, "Your query produced no matching results"),
        ),
        pytest.raises(ERDDAPHTTPError, match="no matching results") as exc_info,
    ):
        retrieve_dataframe(server, "test_dataset", {}, [])

    assert exc_info.value.__cause__.response.status_code == 404
