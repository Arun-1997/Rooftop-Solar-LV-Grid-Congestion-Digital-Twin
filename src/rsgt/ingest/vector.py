"""Helpers for vector ingest: AOI clipping, saving, and a generic WFS source.

Used by the BAG and PC6 loaders, which differ only in their WFS URL and feature
type. Outputs are written as GeoPackage (typed, compact); empty results fall back
to an empty GeoJSON so downstream steps always find a file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from ..config.schema import WFSSourceConfig
from ..geo.crs import RD_NEW
from .clients import WFSClient, features_to_gdf
from .manifest import DownloadManifest

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd

    from .aoi import AreaOfInterest

log = logging.getLogger("rsgt.vector")


def clip_to_aoi(gdf: gpd.GeoDataFrame, aoi: AreaOfInterest) -> gpd.GeoDataFrame:
    """Keep features intersecting the AOI polygon (full geometries preserved)."""
    if len(gdf) == 0:
        return gdf
    mask = gdf.intersects(aoi.geometry)
    return gdf.loc[mask].copy()


def save_vector(gdf: gpd.GeoDataFrame, path_stem: str | Path) -> Path:
    """Write a GeoDataFrame to ``<stem>.gpkg`` (or empty ``<stem>.geojson``)."""
    stem = Path(path_stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    if len(gdf) == 0:
        out = stem.with_suffix(".geojson")
        out.write_text(
            json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
        )
        return out
    out = stem.with_suffix(".gpkg")
    gdf.to_file(out, driver="GPKG")
    return out


def ingest_wfs_source(
    source_name: str,
    cfg: WFSSourceConfig,
    aoi: AreaOfInterest,
    session: requests.Session,
    manifest: DownloadManifest,
    out_dir: str | Path,
    *,
    timeout: float = 60.0,
    force: bool = False,
) -> dict:
    """Fetch every configured WFS feature type within the AOI and save per type."""
    out_dir = Path(out_dir)
    client = WFSClient(session, timeout=timeout)
    layers: dict[str, dict] = {}
    total = 0

    for type_name in cfg.type_names:
        safe = type_name.replace(":", "_")
        stem = out_dir / f"{aoi.name}_{safe}"
        key = f"{source_name}:{type_name}:{aoi.name}"

        if not force and manifest.is_cached(key):
            log.info("%s %s cache hit", source_name, type_name)
            layers[type_name] = {"status": "cached"}
            continue

        features = client.get_features(
            cfg.wfs_url,
            type_name,
            bbox=aoi.bbox,
            crs=RD_NEW,
            page_size=cfg.page_size,
        )
        gdf = features_to_gdf(features, RD_NEW)
        gdf = clip_to_aoi(gdf, aoi)
        out_path = save_vector(gdf, stem)
        manifest.record(
            key=key,
            source=source_name,
            url=cfg.wfs_url,
            path=out_path,
            params={"typeName": type_name, "bbox": list(aoi.bbox), "srsName": RD_NEW},
            content_type="application/geopackage+sqlite3",
            note=f"{len(gdf)} features after AOI clip",
        )
        layers[type_name] = {"status": "ok", "features": int(len(gdf)), "path": str(out_path)}
        total += int(len(gdf))

    return {"source": source_name, "status": "ok", "features": total, "layers": layers}
