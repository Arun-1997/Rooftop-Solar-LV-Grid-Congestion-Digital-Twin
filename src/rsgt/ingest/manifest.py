"""Download manifest for reproducible, cached ingest.

Every downloaded artefact is recorded in ``<raw>/manifest.json`` with its source
URL, request parameters, sha256, byte size and timestamp. A subsequent run can
skip a download whose output file still exists and (optionally) still hashes to
the recorded value, giving cheap reproducibility without re-fetching gigabytes.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    """Stream-hash a file and return its hex sha256."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class ManifestEntry:
    key: str
    source: str
    url: str
    path: str  # relative to the manifest's directory
    bytes: int
    sha256: str
    content_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    downloaded_at: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DownloadManifest:
    """JSON-backed map of ``key -> ManifestEntry`` stored next to the raw data.

    Thread-safe for the modest concurrency the ingest pipeline uses.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.root = self.path.parent
        self._entries: dict[str, ManifestEntry] = {}
        self._lock = threading.Lock()
        if self.path.is_file():
            self._load()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        for key, raw in data.get("entries", {}).items():
            self._entries[key] = ManifestEntry(**raw)

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entries": {k: e.to_dict() for k, e in self._entries.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        tmp.replace(self.path)

    def get(self, key: str) -> ManifestEntry | None:
        return self._entries.get(key)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def is_cached(self, key: str, *, verify: bool = False) -> bool:
        """True if ``key`` is recorded and its file still exists (and matches sha256
        when ``verify`` is set)."""
        entry = self._entries.get(key)
        if entry is None:
            return False
        fpath = self.root / entry.path
        if not fpath.is_file():
            return False
        if fpath.stat().st_size != entry.bytes:
            return False
        if verify and sha256_file(fpath) != entry.sha256:
            return False
        return True

    def record(
        self,
        *,
        key: str,
        source: str,
        url: str,
        path: str | Path,
        params: dict[str, Any] | None = None,
        content_type: str = "",
        note: str = "",
    ) -> ManifestEntry:
        """Hash ``path`` and store/replace its manifest entry. ``path`` may be
        absolute or relative to the manifest root; it is stored relative."""
        abspath = Path(path)
        if not abspath.is_absolute():
            abspath = self.root / abspath
        rel = abspath.relative_to(self.root).as_posix()
        entry = ManifestEntry(
            key=key,
            source=source,
            url=url,
            path=rel,
            bytes=abspath.stat().st_size,
            sha256=sha256_file(abspath),
            content_type=content_type,
            params=params or {},
            downloaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            note=note,
        )
        with self._lock:
            self._entries[key] = entry
        return entry

    def entries(self) -> list[ManifestEntry]:
        return list(self._entries.values())
