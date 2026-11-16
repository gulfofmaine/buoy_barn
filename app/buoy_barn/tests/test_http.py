"""Tests for the shared HTTP client and User-Agent."""

import os
import subprocess
import sys

import httpx2
import pytest
from django.conf import settings

from buoy_barn import http


def _echo_ua(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, text=request.headers.get("user-agent", ""))


def test_user_agent_format():
    assert settings.USER_AGENT.startswith("buoy-barn/")
    assert settings.APP_VERSION in settings.USER_AGENT
    assert settings.USER_AGENT.endswith(f"({settings.USER_AGENT_CONTACT})")


def test_user_agent_contact_override():
    # Settings are read at import time, so load them in a fresh interpreter.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from buoy_barn import settings; print(settings.USER_AGENT)",
        ],
        env={**os.environ, "USER_AGENT_CONTACT": "ops@example.org"},
        cwd=settings.BASE_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        result.stdout.strip() == f"buoy-barn/{settings.APP_VERSION} (ops@example.org)"
    )


def test_client_kwargs_defaults():
    kwargs = http.client_kwargs()
    assert kwargs["headers"]["User-Agent"] == settings.USER_AGENT
    assert kwargs["follow_redirects"] is True
    assert kwargs["timeout"] == settings.ERDDAP_TIMEOUT_SECONDS


def test_client_kwargs_overrides():
    kwargs = http.client_kwargs(timeout=3)
    assert kwargs["timeout"] == 3


def test_client_kwargs_sends_user_agent():
    with httpx2.Client(
        transport=httpx2.MockTransport(_echo_ua),
        **http.client_kwargs(),
    ) as client:
        assert client.get("https://example.org/").text == settings.USER_AGENT


def test_proxy_client_sends_user_agent():
    from deployments.views import _proxy_http_client

    assert _proxy_http_client.headers["user-agent"] == settings.USER_AGENT


def test_get_client_sends_user_agent_and_is_cached(monkeypatch):
    monkeypatch.setattr(http, "_clients", {})
    client = http.get_client()
    assert client is http.get_client()
    assert client.headers["user-agent"] == settings.USER_AGENT
    assert client.follow_redirects is True


def test_get_client_rebuilt_after_pid_change(monkeypatch):
    monkeypatch.setattr(http, "_clients", {})
    monkeypatch.setattr(http.os, "getpid", lambda: 1001)
    parent = http.get_client()
    monkeypatch.setattr(http.os, "getpid", lambda: 1002)
    child = http.get_client()
    assert parent is not child


def test_get_uses_client_and_timeout(monkeypatch):
    monkeypatch.setattr(http, "_clients", {})
    client = http.get_client()
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["ua"] = request.headers["user-agent"]
        seen["timeout"] = request.extensions["timeout"]
        return httpx2.Response(200, text="ok")

    monkeypatch.setattr(client, "_transport", httpx2.MockTransport(handler))
    response = http.get("https://example.org/", timeout=7)
    assert response.text == "ok"
    assert seen["ua"] == settings.USER_AGENT
    assert seen["timeout"]["read"] == 7


def test_raise_for_erddap_status_ok():
    response = httpx2.Response(
        200,
        text="fine",
        request=httpx2.Request("GET", "https://e.org/"),
    )
    http.raise_for_erddap_status(response)


def test_raise_for_erddap_status_keeps_body_and_response():
    response = httpx2.Response(
        404,
        text="Error: Your query produced no matching results",
        request=httpx2.Request("GET", "https://e.org/"),
    )
    with pytest.raises(http.ERDDAPHTTPError) as exc_info:
        http.raise_for_erddap_status(response)
    error = exc_info.value
    assert str(error) == "Error: Your query produced no matching results"
    assert isinstance(error.__cause__, httpx2.HTTPStatusError)
    assert error.__cause__.response.status_code == 404


def test_stac_io_sends_user_agent(monkeypatch):
    monkeypatch.setattr(http, "_clients", {})
    client = http.get_client()
    monkeypatch.setattr(client, "_transport", httpx2.MockTransport(_echo_ua))
    assert (
        http.BuoyBarnStacIO().read_text_from_href("https://example.org/c.json")
        == settings.USER_AGENT
    )


def test_stac_io_reads_local_files(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{}")
    assert http.BuoyBarnStacIO().read_text_from_href(str(path)) == "{}"
