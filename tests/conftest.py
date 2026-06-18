"""Shared test fixtures: a tiny fake ``requests`` session.

Keeps the unit tests offline and dependency-light (no ``responses`` needed). A
handler callable maps ``(url, params) -> FakeResponse`` so tests can model
pagination and per-endpoint behaviour.
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit


class FakeResponse:
    def __init__(
        self,
        *,
        json_data: Any = None,
        content: bytes = b"",
        headers: dict | None = None,
        status_code: int = 200,
        url: str = "http://test/",
        text: str = "",
    ):
        self._json = json_data
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code
        self.url = url
        self.text = text or (content.decode("utf-8", "replace") if content else "")

    def json(self) -> Any:
        if self._json is not None:
            return self._json
        return _json.loads(self.content.decode("utf-8"))

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int = 65536):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i : i + chunk_size]

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc) -> None:
        return None


Handler = Callable[[str, dict | None], FakeResponse]


class FakeSession:
    """Minimal stand-in for ``requests.Session`` used by the ingest clients."""

    def __init__(self, handler: Handler):
        self.handler = handler
        self.headers: dict = {}
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url: str, params: dict | None = None, timeout=None, stream=False, **kw):
        self.calls.append((url, params))
        return self.handler(url, params)

    def mount(self, *a, **k):  # pragma: no cover - parity with requests.Session
        pass


def query_of(url: str) -> dict:
    """Parse the (single-valued) query string of a URL into a plain dict."""
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# --- network test gating ----------------------------------------------------
def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests marked 'network' that hit live Dutch open-data services.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    import pytest

    skip = pytest.mark.skip(reason="needs --run-network (live services)")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
