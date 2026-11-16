"""Shared HTTP client configuration.

Every outbound request from Buoy Barn should go through here so that upstream servers see a
`buoy-barn/...` User-Agent and one HTTP library (httpx2) is used throughout.
"""

import os
import threading
from typing import Any

import httpx2
from django.conf import settings
from pystac.stac_io import DefaultStacIO, _is_url


def client_kwargs(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for building an httpx2 client (sync or async)."""
    kwargs: dict[str, Any] = {
        "headers": {"User-Agent": settings.USER_AGENT},
        "follow_redirects": True,
        "timeout": settings.ERDDAP_TIMEOUT_SECONDS,
    }
    kwargs.update(overrides)
    return kwargs


# One client per process id, so Celery prefork children never share a connection pool
# that was created in the parent.
_clients: dict[int, httpx2.Client] = {}
_clients_lock = threading.Lock()


def get_client() -> httpx2.Client:
    """Lazily created sync client for this process."""
    pid = os.getpid()
    with _clients_lock:
        client = _clients.get(pid)
        if client is None:
            client = httpx2.Client(**client_kwargs())
            _clients[pid] = client
        return client


def get(url: str, *, timeout: float | None = None) -> httpx2.Response:
    """GET a URL with the shared client. Tests patch this function."""
    if timeout is None:
        return get_client().get(url)
    return get_client().get(url, timeout=timeout)


class ERDDAPHTTPError(Exception):
    """An ERDDAP server returned an error status.

    Mirrors erddapy's error shape: `str(error)` is the response body, and `__cause__`
    is the `httpx2.HTTPStatusError`, which carries `.response`.
    """


def raise_for_erddap_status(response: httpx2.Response) -> None:
    """Raise `ERDDAPHTTPError` for 4xx/5xx responses."""
    try:
        response.raise_for_status()
    except httpx2.HTTPStatusError as error:
        raise ERDDAPHTTPError(response.text) from error


class BuoyBarnStacIO(DefaultStacIO):
    """pystac IO that fetches URLs through the shared client."""

    def read_text_from_href(self, href: str) -> str:
        if _is_url(href):
            response = get(href)
            response.raise_for_status()
            return response.text
        return super().read_text_from_href(href)
