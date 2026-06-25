"""Export roof-plane yields to GeoJSON (WGS84) for the web map."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..geo.crs import WGS84

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd

log = logging.getLogger("rsgt.export")

# Columns carried into the web map (kept small for file size).
MAP_FIELDS = [
    "building_id", "plane_id", "bag_id", "area_m2", "usable_area_m2", "tilt_deg",
    "azimuth_deg", "kwp", "specific_yield_kwh_kwp", "annual_kwh", "poa_kwh_m2_yr",
    "bouwjaar", "pc6",
]


def export_roof_geojson(
    gdf: gpd.GeoDataFrame, path: str | Path, *, simplify_m: float = 0.2
) -> Path:
    """Reproject roof planes to WGS84 and write a compact GeoJSON. Returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    g = gdf.copy()
    if simplify_m and len(g):
        # Simplify in metric CRS (RD New) before reprojecting -> smaller file.
        g["geometry"] = g.geometry.simplify(simplify_m, preserve_topology=True)
    g = g.to_crs(WGS84)
    keep = [c for c in MAP_FIELDS if c in g.columns] + ["geometry"]
    g = g[keep]
    g.to_file(path, driver="GeoJSON")
    log.info("export: wrote %d roof planes to %s", len(g), path.name)
    return path
