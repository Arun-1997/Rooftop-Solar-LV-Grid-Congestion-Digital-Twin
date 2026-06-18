"""HTTP session and cached file downloads.

A single :class:`requests.Session` with retry/backoff is shared across the ingest
run. :func:`download_file` streams to a temp file, moves it into place atomically,
and records the result in the :class:`DownloadManifest` so re-runs are cheap.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config.schema import HTTPConfig
from .manifest import DownloadManifest

log = logging.getLogger("rsgt.download")


def build_session(http: HTTPConfig) -> requests.Session:
    """Create a session with retries on transient errors and a project UA."""
    session = requests.Session()
    retry = Retry(
        total=http.max_retries,
        connect=http.max_retries,
        read=http.max_retries,
        status=http.max_retries,
        backoff_factor=http.backoff_s,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": http.user_agent})
    return session


def download_file(
    session: requests.Session,
    url: str,
    dest: str | Path,
    *,
    manifest: DownloadManifest,
    key: str,
    source: str,
    params: dict[str, Any] | None = None,
    timeout: float = 60.0,
    force: bool = False,
    note: str = "",
) -> Path:
    """Download ``url`` (with optional query ``params``) to ``dest``.

    Skips the download when the manifest already has ``key`` and the output file is
    present and the right size. Returns the path to the file.
    """
    dest = Path(dest)
    if not force and manifest.is_cached(key):
        log.info("cache hit  %s -> %s", key, dest.name)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("downloading %s", key)
    with session.get(url, params=params, timeout=timeout, stream=True) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
    os.replace(tmp, dest)
    manifest.record(
        key=key,
        source=source,
        url=resp.url,
        path=dest,
        params=params or {},
        content_type=content_type,
        note=note,
    )
    return dest


def write_bytes(
    data: bytes,
    dest: str | Path,
    *,
    manifest: DownloadManifest,
    key: str,
    source: str,
    url: str,
    params: dict[str, Any] | None = None,
    content_type: str = "",
    note: str = "",
) -> Path:
    """Persist already-fetched ``data`` to ``dest`` and record it in the manifest.

    Used for responses assembled in memory (paged WFS/OGC features, mosaics).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, dest)
    manifest.record(
        key=key,
        source=source,
        url=url,
        path=dest,
        params=params or {},
        content_type=content_type,
        note=note,
    )
    return dest
