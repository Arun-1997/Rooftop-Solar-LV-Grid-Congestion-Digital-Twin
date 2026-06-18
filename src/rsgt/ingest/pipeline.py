"""Stage 0 orchestrator: resolve the AOI and ingest every enabled source.

Each source runs independently and its failure is captured (not raised) so one
flaky service does not abort the whole run. A machine-readable run summary is
written to ``<processed>/ingest_summary.json`` and the download manifest lives at
``<raw>/manifest.json``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config.schema import RunConfig
from .ahn import ingest_ahn
from .aoi import AreaOfInterest, resolve_aoi
from .bag import ingest_bag
from .bag3d import ingest_bag3d
from .capacity import ingest_capacity
from .download import build_session
from .manifest import DownloadManifest
from .pc6 import ingest_pc6

log = logging.getLogger("rsgt.pipeline")

ALL_SOURCES = ("bag3d", "ahn", "bag", "pc6", "capacity")


@dataclass
class Paths:
    base: Path
    root: Path
    raw: Path
    interim: Path
    processed: Path

    @classmethod
    def from_config(cls, cfg: RunConfig, base_dir: str | Path) -> Paths:
        base = Path(base_dir).resolve()
        root = base / cfg.paths.root
        return cls(
            base=base,
            root=root,
            raw=root / cfg.paths.raw,
            interim=root / cfg.paths.interim,
            processed=root / cfg.paths.processed,
        )

    def ensure(self) -> None:
        for p in (self.raw, self.interim, self.processed):
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class IngestSummary:
    aoi_name: str
    aoi_source: str = ""
    aoi_bbox: tuple[float, float, float, float] | None = None
    started_at: str = ""
    finished_at: str = ""
    results: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "aoi": {
                "name": self.aoi_name,
                "source": self.aoi_source,
                "bbox_rd": list(self.aoi_bbox) if self.aoi_bbox else None,
            },
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results": self.results,
        }


def run_ingest(
    cfg: RunConfig,
    *,
    base_dir: str | Path = ".",
    only: Iterable[str] | None = None,
    force: bool = False,
) -> IngestSummary:
    """Run Stage 0 ingest for ``cfg`` and return a summary.

    ``only`` restricts which sources run (subset of :data:`ALL_SOURCES`).
    """
    selected = set(only) if only else set(ALL_SOURCES)
    unknown = selected - set(ALL_SOURCES)
    if unknown:
        raise ValueError(f"Unknown sources requested: {sorted(unknown)}")

    paths = Paths.from_config(cfg, base_dir)
    paths.ensure()
    session = build_session(cfg.http)
    manifest = DownloadManifest(paths.raw / "manifest.json")
    summary = IngestSummary(
        aoi_name=cfg.aoi.name,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    # --- AOI (always needed) -------------------------------------------------
    aoi: AreaOfInterest = resolve_aoi(
        cfg.aoi, cfg.sources.boundary, session, timeout=cfg.http.timeout_s
    )
    aoi.save(paths.interim / f"{aoi.name}_aoi.geojson")
    summary.aoi_source = aoi.source
    summary.aoi_bbox = aoi.bbox
    log.info("AOI '%s' [%s] bbox=%s", aoi.name, aoi.source, aoi.bbox)

    # --- Sources -------------------------------------------------------------
    dispatch = {
        "bag3d": lambda: ingest_bag3d(
            aoi, cfg.sources.bag3d, session, manifest, paths.raw / "bag3d",
            timeout=cfg.http.timeout_s, force=force,
        ),
        "ahn": lambda: ingest_ahn(
            aoi, cfg.sources.ahn, session, manifest, paths.raw / "ahn",
            timeout=max(cfg.http.timeout_s, 120.0), force=force,
        ),
        "bag": lambda: ingest_bag(
            aoi, cfg.sources.bag, session, manifest, paths.raw / "bag",
            timeout=cfg.http.timeout_s, force=force,
        ),
        "pc6": lambda: ingest_pc6(
            aoi, cfg.sources.pc6, session, manifest, paths.raw / "pc6",
            timeout=cfg.http.timeout_s, force=force,
        ),
        "capacity": lambda: ingest_capacity(
            aoi, cfg.sources.capacity, session, manifest, paths.raw / "capacity",
            timeout=cfg.http.timeout_s, force=force,
        ),
    }
    enabled = {
        "bag3d": cfg.sources.bag3d.enabled,
        "ahn": cfg.sources.ahn.enabled,
        "bag": cfg.sources.bag.enabled,
        "pc6": cfg.sources.pc6.enabled,
        "capacity": cfg.sources.capacity.enabled,
    }

    for name in ALL_SOURCES:
        if name not in selected:
            continue
        if not enabled[name]:
            summary.results[name] = {"source": name, "status": "disabled"}
            log.info("%s: disabled in config", name)
            continue
        try:
            summary.results[name] = dispatch[name]()
        except Exception as exc:  # noqa: BLE001 — isolate per-source failures
            log.exception("%s ingest failed", name)
            summary.results[name] = {"source": name, "status": "error", "error": str(exc)}
        finally:
            manifest.save()

    summary.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_summary(summary, paths.processed / "ingest_summary.json")
    return summary


def _write_summary(summary: IngestSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(summary.to_dict(), fh, indent=2, ensure_ascii=False)
