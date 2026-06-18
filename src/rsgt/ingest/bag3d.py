"""Ingest 3D BAG LoD2.2 building geometry.

The 3D BAG OGC API (``api.3dbag.nl``) serves **CityJSONFeature** objects, paged by
``next`` links. Each page carries its own CityJSON ``transform`` (scale/translate)
against which that page's integer vertices are quantised — and the transform
*changes between pages*. To emit a single, standards-valid **CityJSONSeq** file
(line 1 = CityJSON header, each subsequent line = one CityJSONFeature) we re-quantise
every page's vertices onto the first page's transform.

Output: ``<raw>/bag3d/<aoi>.city.jsonl`` (CityJSONSeq, EPSG:7415) plus a building-id
list. Parsing roof planes from it is P1's job; P0 only fetches and assembles.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests

from ..config.schema import Bag3DConfig
from .aoi import AreaOfInterest
from .clients import OGCFeaturesClient
from .manifest import DownloadManifest

log = logging.getLogger("rsgt.bag3d")

Vertex = list[int]
Transform = dict[str, list[float]]


def requantize_vertex(v: Vertex, src: Transform, dst: Transform) -> Vertex:
    """Move an integer vertex from the ``src`` quantisation to ``dst``.

    real = v*src.scale + src.translate ; out = round((real - dst.translate)/dst.scale).
    Exact up to <=0.5 * dst.scale rounding (sub-millimetre for 3D BAG's 0.001 m).
    """
    ss, st = src["scale"], src["translate"]
    ds, dt = dst["scale"], dst["translate"]
    return [round((v[i] * ss[i] + st[i] - dt[i]) / ds[i]) for i in range(3)]


def _rewrite_feature(feature: dict, src: Transform, dst: Transform) -> dict:
    if src == dst:
        return feature
    feature = dict(feature)
    feature["vertices"] = [requantize_vertex(v, src, dst) for v in feature.get("vertices", [])]
    return feature


def _header_from_metadata(metadata: dict) -> dict:
    """Build the CityJSONSeq header line from a page's ``metadata`` object."""
    return {
        "type": "CityJSON",
        "version": metadata.get("version", "2.0"),
        "transform": metadata["transform"],
        "metadata": metadata.get("metadata", {}),
        "CityObjects": {},
        "vertices": [],
    }


def ingest_bag3d(
    aoi: AreaOfInterest,
    cfg: Bag3DConfig,
    session: requests.Session,
    manifest: DownloadManifest,
    out_dir: str | Path,
    *,
    timeout: float = 60.0,
    force: bool = False,
) -> dict:
    """Fetch all 3D BAG buildings intersecting the AOI bbox into a CityJSONSeq file."""
    out_dir = Path(out_dir)
    out_path = out_dir / f"{aoi.name}.city.jsonl"
    ids_path = out_dir / f"{aoi.name}_buildings.txt"
    key = f"bag3d:{aoi.name}"

    if not force and manifest.is_cached(key) and ids_path.is_file():
        n = sum(1 for _ in ids_path.open("r", encoding="utf-8"))
        log.info("bag3d cache hit (%d buildings)", n)
        return {"source": "bag3d", "status": "cached", "buildings": n, "path": str(out_path)}

    client = OGCFeaturesClient(session, timeout=timeout)
    items_url = f"{cfg.api_url}/collections/{cfg.collection}/items"
    params = client.bbox_params(aoi.bbox, cfg.bbox_crs, cfg.page_size)

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    header_transform: Transform | None = None
    seen: set[str] = set()
    n_written = 0

    with tmp.open("w", encoding="utf-8") as fh, ids_path.open("w", encoding="utf-8") as ids_fh:
        for page in client.iter_pages(items_url, params, max_items=cfg.max_features):
            metadata = page.get("metadata")
            if metadata is None:
                continue
            if header_transform is None:
                header = _header_from_metadata(metadata)
                header_transform = header["transform"]
                fh.write(json.dumps(header, ensure_ascii=False) + "\n")
            src_transform = metadata["transform"]
            for feature in page.get("features", []):
                fid = feature.get("id")
                if fid in seen:
                    continue
                seen.add(fid)
                fh.write(
                    json.dumps(_rewrite_feature(feature, src_transform, header_transform),
                               ensure_ascii=False)
                    + "\n"
                )
                ids_fh.write(f"{fid}\n")
                n_written += 1

    if header_transform is None:
        # No buildings in the AOI: still leave a valid (empty) artefact.
        tmp.write_text("", encoding="utf-8")
        log.warning("bag3d: no buildings found in AOI bbox %s", aoi.bbox)

    os.replace(tmp, out_path)
    manifest.record(
        key=key,
        source="bag3d",
        url=items_url,
        path=out_path,
        params={"bbox": list(aoi.bbox), "bbox-crs": cfg.bbox_crs},
        content_type="application/city+json-seq",
        note=f"{n_written} CityJSONFeatures (CityJSONSeq, EPSG:7415)",
    )
    log.info("bag3d: wrote %d buildings to %s", n_written, out_path.name)
    return {
        "source": "bag3d",
        "status": "ok",
        "buildings": n_written,
        "path": str(out_path),
    }
