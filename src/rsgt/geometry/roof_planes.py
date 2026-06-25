"""Extract usable roof planes from the 3D BAG CityJSONSeq.

For every building we read its LoD2.2 ``RoofSurface`` polygons and compute, *from
the geometry itself* (not the dataset's derived attributes), each plane's:

* **area** (true 3D surface area, m^2),
* **tilt** (slope from horizontal, deg: 0 = flat, 90 = vertical),
* **azimuth** (compass bearing the plane faces, deg: 0 = N, 90 = E, 180 = S),
* horizontal **footprint** polygon (RD New) for mapping.

The surface normal is found with Newell's method, which is robust for the slightly
non-planar rings real roofs have. Planes that are too small, or steep *and* facing
north, are dropped as non-viable for PV.

Output: a GeoDataFrame (and ``<processed>/<aoi>_roof_planes.gpkg``) of one row per
roof plane, in EPSG:28992.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING

from ..config.schema import RD_NEW, RoofConfig
from .cityjson import Coord, decode_vertices, iter_features, iter_semantic_surfaces, read_header

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd

log = logging.getLogger("rsgt.geometry")

BAG_PREFIX = "NL.IMBAG.Pand."


# --------------------------------------------------------------------- geometry
def newell_normal(coords: list[Coord]) -> tuple[float, float, float]:
    """Area-weighted polygon normal via Newell's method (handles non-planar rings)."""
    nx = ny = nz = 0.0
    n = len(coords)
    for i in range(n):
        x0, y0, z0 = coords[i]
        x1, y1, z1 = coords[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return nx, ny, nz


def polygon_area_3d(coords: list[Coord]) -> float:
    """True 3D area of a planar polygon (half the Newell normal's magnitude)."""
    nx, ny, nz = newell_normal(coords)
    return 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)


def normal_to_tilt_azimuth(nx: float, ny: float, nz: float) -> tuple[float, float]:
    """Convert a surface normal to (tilt_deg, azimuth_deg).

    Azimuth uses the compass/pvlib convention (0=N, 90=E, 180=S, 270=W); in RD New
    +x is East and +y is North. For (near-)flat planes the azimuth is ill-defined
    but irrelevant to yield, so we return 180 (south) by convention.
    """
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag < 1e-12:
        return 0.0, 180.0
    ux, uy, uz = nx / mag, ny / mag, nz / mag
    if uz < 0:  # make the normal point up
        ux, uy, uz = -ux, -uy, -uz
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, uz))))
    if math.hypot(ux, uy) < 1e-9:
        return tilt, 180.0
    azimuth = math.degrees(math.atan2(ux, uy)) % 360.0
    return tilt, azimuth


def _ring_centroid(coords: list[Coord]) -> Coord:
    n = len(coords)
    return (sum(c[0] for c in coords) / n, sum(c[1] for c in coords) / n,
            sum(c[2] for c in coords) / n)


# ------------------------------------------------------------------- extraction
def extract_roof_planes(path: str | Path, lod: str = "2.2") -> gpd.GeoDataFrame:
    """Read all roof planes from a CityJSONSeq into a GeoDataFrame (EPSG:28992)."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    transform = read_header(path)
    records: list[dict] = []
    geoms: list = []
    if transform is None:
        log.warning("roof extraction: %s has no header (empty); 0 planes", path)
        return gpd.GeoDataFrame(records, geometry=geoms, crs=RD_NEW)

    for feature in iter_features(path):
        verts = decode_vertices(feature, transform)
        for obj_id, obj in feature["CityObjects"].items():
            parents = obj.get("parents")
            building_id = parents[0] if parents else obj_id
            bag_id = building_id.split(".")[-1]
            for geom in obj.get("geometry", []):
                if str(geom.get("lod")) != lod:
                    continue
                idx = 0
                for surf_type, boundary in iter_semantic_surfaces(geom):
                    if surf_type != "RoofSurface":
                        continue
                    ring = [verts[i] for i in boundary[0]]
                    if len(ring) < 3:
                        continue
                    nx, ny, nz = newell_normal(ring)
                    area = 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)
                    if area < 1e-6:
                        continue
                    tilt, azimuth = normal_to_tilt_azimuth(nx, ny, nz)
                    cx, cy, cz = _ring_centroid(ring)
                    footprint = Polygon([(x, y) for x, y, _ in ring])
                    if not footprint.is_valid:
                        footprint = footprint.buffer(0)
                    records.append({
                        "building_id": building_id,
                        "bag_id": bag_id,
                        "plane_id": f"{bag_id}::r{idx}",
                        "area_m2": round(area, 3),
                        "tilt_deg": round(tilt, 2),
                        "azimuth_deg": round(azimuth, 1),
                        "centroid_x": round(cx, 3),
                        "centroid_y": round(cy, 3),
                        "centroid_z": round(cz, 3),
                        "n_vertices": len(ring),
                    })
                    geoms.append(footprint)
                    idx += 1

    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs=RD_NEW)
    log.info("roof extraction: %d planes from %s", len(gdf), Path(path).name)
    return gdf


def filter_planes(gdf: gpd.GeoDataFrame, cfg: RoofConfig) -> gpd.GeoDataFrame:
    """Drop planes that are too small, too steep, or steep-and-north-facing."""
    if len(gdf) == 0:
        return gdf
    keep = gdf["area_m2"] >= cfg.min_area_m2
    keep &= gdf["tilt_deg"] <= cfg.max_tilt_deg
    if cfg.drop_north_steep:
        lo, hi = cfg.north_azimuth_range  # e.g. (315, 45) wraps through 0
        north = (gdf["azimuth_deg"] >= lo) | (gdf["azimuth_deg"] <= hi)
        steep = gdf["tilt_deg"] >= cfg.steep_tilt_deg
        keep &= ~(north & steep)
    out = gdf.loc[keep].reset_index(drop=True)
    log.info("roof filter: kept %d / %d planes", len(out), len(gdf))
    return out
