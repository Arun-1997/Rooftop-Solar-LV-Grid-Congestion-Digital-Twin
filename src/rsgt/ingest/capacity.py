"""Ingest the Netbeheer Nederland capaciteitskaart (the ground-truth congestion data).

This is the project's credibility anchor: per-PC6 feed-in (*invoeding*) and
consumption (*afname*) headroom, published as an ArcGIS Feature Service. The exact
FeatureServer URL and layer ids are not exposed as a static link, so they must be
set in the run config (read them off the public map's network requests). Until
then this source is disabled and skipped with an explanatory status — it is *not*
treated as a failure.

NB (per the spec): the capacity map must stay **held-out external validation** for
the congestion flags, never a training target.
"""

from __future__ import annotations

import logging

import requests

from ..config.schema import CapacityConfig
from ..geo.crs import RD_NEW
from .aoi import AreaOfInterest
from .clients import ArcGISFeatureServiceClient, features_to_gdf
from .manifest import DownloadManifest
from .vector import clip_to_aoi, save_vector

log = logging.getLogger("rsgt.capacity")


def ingest_capacity(
    aoi: AreaOfInterest,
    cfg: CapacityConfig,
    session: requests.Session,
    manifest: DownloadManifest,
    out_dir,
    *,
    timeout: float = 60.0,
    force: bool = False,
) -> dict:
    from pathlib import Path

    out_dir = Path(out_dir)

    if not cfg.feature_server:
        msg = (
            "capacity.feature_server not configured; skipping. Set the ArcGIS "
            "FeatureServer URL and invoeding/afname layer ids in the run config "
            "(find them in the capaciteitskaart map's network requests)."
        )
        log.warning(msg)
        return {"source": "capacity", "status": "skipped", "reason": msg}

    client = ArcGISFeatureServiceClient(session, timeout=timeout)
    layers: dict[str, dict] = {}
    jobs = []
    if cfg.invoeding_layer is not None:
        jobs.append(("invoeding", cfg.invoeding_layer))
    if cfg.afname_layer is not None:
        jobs.append(("afname", cfg.afname_layer))
    if not jobs:
        return {
            "source": "capacity",
            "status": "skipped",
            "reason": "no invoeding/afname layer ids configured",
        }

    base = cfg.feature_server.rstrip("/")
    for kind, layer_id in jobs:
        stem = out_dir / f"{aoi.name}_capacity_{kind}"
        key = f"capacity:{kind}:{aoi.name}"
        if not force and manifest.is_cached(key):
            layers[kind] = {"status": "cached"}
            continue
        layer_url = f"{base}/{layer_id}"
        features = client.query_layer(
            layer_url,
            bbox=aoi.bbox,
            in_sr=28992,
            out_sr=28992,
            page_size=cfg.page_size,
        )
        gdf = features_to_gdf(features, RD_NEW)
        gdf = clip_to_aoi(gdf, aoi)
        out_path = save_vector(gdf, stem)
        manifest.record(
            key=key,
            source="capacity",
            url=layer_url,
            path=out_path,
            params={"bbox": list(aoi.bbox), "layer": layer_id},
            content_type="application/geopackage+sqlite3",
            note=f"{len(gdf)} {kind} features (held-out validation only)",
        )
        layers[kind] = {"status": "ok", "features": int(len(gdf)), "path": str(out_path)}

    return {"source": "capacity", "status": "ok", "layers": layers}
