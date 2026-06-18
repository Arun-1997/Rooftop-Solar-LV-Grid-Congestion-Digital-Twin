"""Ingest AHN elevation rasters (DSM/DTM) via the PDOK WCS.

The AHN coverages are 0.5 m. A whole municipality at 0.5 m is far larger than any
single WCS request allows, so the AOI bbox is split into tiles, each fetched with
``GetCoverage``, then mosaicked into one GeoTIFF per coverage.

Output: ``<raw>/ahn/<aoi>_dsm.tif`` and ``<aoi>_dtm.tif`` (EPSG:28992). The DSM is
the surface needed for P2 shading; the DTM supports ground-height normalisation.
Raw LAZ point-cloud download is available but off by default (it is large).
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from ..config.schema import AHNConfig
from ..geo.crs import tile_bbox
from .aoi import AreaOfInterest
from .clients import WCSClient
from .manifest import DownloadManifest

log = logging.getLogger("rsgt.ahn")


def _fetch_coverage_mosaic(
    client: WCSClient,
    cfg: AHNConfig,
    coverage_id: str,
    aoi: AreaOfInterest,
    out_path: Path,
    work_dir: Path,
) -> None:
    """Tile the AOI bbox, GetCoverage each tile, and mosaic to ``out_path``."""
    import rasterio
    from rasterio.merge import merge

    tiles = tile_bbox(aoi.bbox, cfg.tile_size_m)
    log.info("AHN %s: %d WCS tile(s)", coverage_id, len(tiles))
    work_dir.mkdir(parents=True, exist_ok=True)
    tile_paths: list[Path] = []
    for i, tb in enumerate(tiles):
        data = client.get_coverage(cfg.wcs_url, coverage_id, tb)
        tp = work_dir / f"{aoi.name}_{coverage_id}_{i:04d}.tif"
        tp.write_bytes(data)
        tile_paths.append(tp)

    if len(tile_paths) == 1:
        tile_paths[0].replace(out_path)
        return

    srcs = [rasterio.open(p) for p in tile_paths]
    try:
        mosaic, transform = merge(srcs)
        meta = srcs[0].meta.copy()
        meta.update(
            height=mosaic.shape[1],
            width=mosaic.shape[2],
            transform=transform,
            count=mosaic.shape[0],
        )
        with rasterio.open(out_path, "w", **meta) as dst:
            dst.write(mosaic)
    finally:
        for s in srcs:
            s.close()
    for tp in tile_paths:
        tp.unlink(missing_ok=True)


def ingest_ahn(
    aoi: AreaOfInterest,
    cfg: AHNConfig,
    session: requests.Session,
    manifest: DownloadManifest,
    out_dir: str | Path,
    *,
    timeout: float = 120.0,
    force: bool = False,
) -> dict:
    """Download AHN DSM/DTM rasters clipped to the AOI bbox."""
    out_dir = Path(out_dir)
    work_dir = out_dir / "_wcs_tiles"
    client = WCSClient(session, timeout=timeout)
    result: dict = {"source": "ahn", "status": "ok", "version": cfg.version, "rasters": {}}

    jobs = []
    if cfg.download_dsm:
        jobs.append(("dsm", cfg.dsm_coverage))
    if cfg.download_dtm:
        jobs.append(("dtm", cfg.dtm_coverage))

    for kind, coverage_id in jobs:
        out_path = out_dir / f"{aoi.name}_{kind}.tif"
        key = f"ahn:{kind}:{aoi.name}"
        if not force and manifest.is_cached(key):
            log.info("ahn %s cache hit", kind)
            result["rasters"][kind] = {"status": "cached", "path": str(out_path)}
            continue
        _fetch_coverage_mosaic(client, cfg, coverage_id, aoi, out_path, work_dir)
        manifest.record(
            key=key,
            source="ahn",
            url=cfg.wcs_url,
            path=out_path,
            params={
                "coverageId": coverage_id,
                "bbox": list(aoi.bbox),
                "version": cfg.version,
            },
            content_type="image/tiff",
            note=f"AHN {cfg.version} {kind} {cfg.resolution_m} m",
        )
        result["rasters"][kind] = {"status": "ok", "path": str(out_path)}

    if cfg.download_laz:
        result["laz"] = {
            "status": "skipped",
            "note": "LAZ tile download is a P2 concern; enable in a dedicated run.",
        }

    # Clean up any leftover tile workspace.
    if work_dir.is_dir() and not any(work_dir.iterdir()):
        work_dir.rmdir()
    return result
