"""Resolve the area of interest (AOI) for a run.

The AOI drives every download: its bbox bounds the WFS/WCS/OGC queries and its
precise polygon is used to clip vector results. It is resolved from either an
explicit RD-New bbox or a municipality name (looked up in the PDOK 'bestuurlijke
gebieden' OGC API Features service), then optionally buffered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from ..config.schema import AOIConfig, BoundaryConfig
from ..geo.crs import RD_NEW, bbox_polygon, buffer_bbox, epsg_uri
from .clients import OGCFeaturesClient

if TYPE_CHECKING:  # pragma: no cover
    from shapely.geometry.base import BaseGeometry

log = logging.getLogger("rsgt.aoi")

BBox = tuple[float, float, float, float]


@dataclass
class AreaOfInterest:
    name: str
    geometry: BaseGeometry  # in RD New (EPSG:28992)
    bbox: BBox
    crs: str = RD_NEW
    source: str = "bbox"

    def to_geojson_dict(self) -> dict:
        from shapely.geometry import mapping

        return {
            "type": "FeatureCollection",
            "name": self.name,
            "crs": {"type": "name", "properties": {"name": f"urn:ogc:def:crs:{self.crs}"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": self.name, "source": self.source},
                    "geometry": mapping(self.geometry),
                }
            ],
        }

    def save(self, path: str | Path) -> Path:
        import json

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(self.to_geojson_dict(), fh, ensure_ascii=False)
        return path


def resolve_municipality_geometry(
    name: str, boundary: BoundaryConfig, session: requests.Session, timeout: float = 60.0
) -> BaseGeometry:
    """Fetch and union the polygon(s) for a municipality from PDOK (in RD New)."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    client = OGCFeaturesClient(session, timeout=timeout)
    params = {
        boundary.name_field: name,
        "f": "json",
        "limit": 50,
        "crs": epsg_uri(RD_NEW),
    }
    features = client.get_geojson_features(boundary.ogc_url, params)
    if not features:
        raise ValueError(f"No municipality found named {name!r} at {boundary.ogc_url}")
    geoms = [shape(f["geometry"]) for f in features if f.get("geometry")]
    return unary_union(geoms)


def resolve_aoi(
    cfg: AOIConfig,
    boundary: BoundaryConfig,
    session: requests.Session,
    *,
    timeout: float = 60.0,
) -> AreaOfInterest:
    """Resolve an :class:`AreaOfInterest` from the AOI config.

    Prefers the municipality boundary; falls back to the configured bbox if the
    lookup fails or no name is given.
    """
    geometry: BaseGeometry | None = None
    source = "bbox"

    if cfg.municipality:
        try:
            geometry = resolve_municipality_geometry(cfg.municipality, boundary, session, timeout)
            source = "municipality"
            log.info("resolved AOI '%s' from municipality boundary", cfg.municipality)
        except Exception as exc:  # noqa: BLE001 — fall back to bbox if available
            if cfg.bbox is None:
                raise
            log.warning(
                "municipality lookup failed (%s); falling back to configured bbox", exc
            )

    if geometry is None:
        if cfg.bbox is None:  # pragma: no cover — schema guarantees one is set
            raise ValueError("AOI has neither a resolvable municipality nor a bbox")
        geometry = bbox_polygon(cfg.bbox)
        source = "bbox"

    if cfg.buffer_m:
        geometry = geometry.buffer(cfg.buffer_m)

    bbox = tuple(round(v, 3) for v in geometry.bounds)  # type: ignore[assignment]

    # If both a municipality and a bbox are configured, the bbox additionally
    # clips the resolved boundary (lets you study just a corner of a town).
    if source == "municipality" and cfg.bbox is not None:
        clip = bbox_polygon(buffer_bbox(cfg.bbox, cfg.buffer_m))
        clipped = geometry.intersection(clip)
        if not clipped.is_empty:
            geometry = clipped
            bbox = tuple(round(v, 3) for v in geometry.bounds)  # type: ignore[assignment]
            source = "municipality+bbox"

    return AreaOfInterest(
        name=cfg.name, geometry=geometry, bbox=bbox, crs=RD_NEW, source=source
    )
