"""P1 orchestrator: roof planes -> physics yield -> map + validation.

Reads P0's artefacts (the 3D BAG CityJSONSeq, BAG attributes, PC6 polygons),
produces per-roof-plane and per-building yield tables, a standalone deck.gl map,
and a PVGIS validation summary. Everything lands under ``<processed>/``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config.schema import RunConfig
from ..geometry.roof_planes import extract_roof_planes, filter_planes
from ..ingest.pipeline import Paths
from .resource import centroid_lonlat, get_tmy, solar_position
from .yield_model import compute_plane_yields

log = logging.getLogger("rsgt.solar")


@dataclass
class YieldSummary:
    aoi_name: str
    started_at: str = ""
    finished_at: str = ""
    result: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "aoi": self.aoi_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
        }


def _bag3d_path(paths: Paths, name: str) -> Path:
    return paths.raw / "bag3d" / f"{name}.city.jsonl"


def run_roofs(cfg: RunConfig, *, base_dir: str | Path = ".", force: bool = False) -> dict:
    """Step 1: extract + filter roof planes -> ``<processed>/<aoi>_roof_planes.gpkg``."""
    paths = Paths.from_config(cfg, base_dir)
    paths.processed.mkdir(parents=True, exist_ok=True)
    out = paths.processed / f"{cfg.aoi.name}_roof_planes.gpkg"
    src = _bag3d_path(paths, cfg.aoi.name)
    if not src.is_file():
        raise FileNotFoundError(
            f"3D BAG file not found: {src} — run `rsgt ingest` (P0) first."
        )
    if out.is_file() and not force:
        import geopandas as gpd

        gdf = gpd.read_file(out)
        log.info("roofs: reusing %s (%d planes)", out.name, len(gdf))
        return {"status": "cached", "planes": int(len(gdf)), "path": str(out)}

    raw = extract_roof_planes(src, lod=cfg.roof.lod)
    planes = filter_planes(raw, cfg.roof)
    _save_planes(planes, out)
    return {
        "status": "ok",
        "planes_raw": int(len(raw)),
        "planes_kept": int(len(planes)),
        "path": str(out),
    }


def _save_planes(planes, out: Path) -> None:
    if len(planes):
        planes.to_file(out, driver="GPKG")
    else:  # keep a valid empty artefact
        out.with_suffix(".geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
        )


def _join_bag(planes, paths: Paths, name: str):
    import geopandas as gpd

    bag_path = paths.raw / "bag" / f"{name}_bag_pand.gpkg"
    if not bag_path.is_file():
        log.warning("BAG attributes not found (%s); skipping bouwjaar join", bag_path.name)
        return planes
    bag = gpd.read_file(bag_path)
    cols = {c.lower(): c for c in bag.columns}
    keep = {}
    if "identificatie" in cols:
        keep["bag_id"] = bag[cols["identificatie"]].astype(str)
    else:
        return planes
    for attr in ("bouwjaar", "gebruiksdoel", "status"):
        if attr in cols:
            keep[attr] = bag[cols[attr]]
    import pandas as pd

    attrs = pd.DataFrame(keep).drop_duplicates("bag_id")
    return planes.merge(attrs, on="bag_id", how="left")


def _join_pc6(planes, paths: Paths, name: str):
    import geopandas as gpd
    from shapely.geometry import Point

    pc6_path = paths.raw / "pc6" / f"{name}_postcode6_postcode6.gpkg"
    if not pc6_path.is_file() or len(planes) == 0:
        log.warning("PC6 polygons not found (%s); skipping pc6 tag", pc6_path.name)
        return planes
    pc6 = gpd.read_file(pc6_path)
    code_col = next((c for c in ("postcode6", "postcode", "pc6") if c in pc6.columns), None)
    if code_col is None:
        return planes
    centroids = gpd.GeoDataFrame(
        {"_idx": range(len(planes))},
        geometry=[
            Point(x, y)
            for x, y in zip(planes["centroid_x"], planes["centroid_y"], strict=False)
        ],
        crs=planes.crs,
    )
    joined = gpd.sjoin(centroids, pc6[[code_col, "geometry"]], how="left", predicate="within")
    joined = joined.drop_duplicates("_idx").set_index("_idx")
    planes = planes.copy()
    planes["pc6"] = joined[code_col].values
    return planes


def run_yield(
    cfg: RunConfig,
    *,
    base_dir: str | Path = ".",
    make_map: bool = True,
    validate: bool = True,
    force: bool = False,
) -> YieldSummary:
    """Full P1: roofs -> resource -> physics -> join -> export -> validate."""
    import geopandas as gpd

    paths = Paths.from_config(cfg, base_dir)
    paths.processed.mkdir(parents=True, exist_ok=True)
    name = cfg.aoi.name
    summary = YieldSummary(
        aoi_name=name, started_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    # 1) roof planes
    roofs = run_roofs(cfg, base_dir=base_dir, force=force)
    summary.result["roofs"] = roofs
    planes_path = paths.processed / f"{name}_roof_planes.gpkg"
    planes = gpd.read_file(planes_path) if planes_path.is_file() else gpd.GeoDataFrame()

    if len(planes) == 0:
        summary.result["yield"] = {"status": "empty", "note": "no roof planes in AOI"}
        summary.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _write_summary(summary, paths.processed / f"{name}_yield_summary.json")
        return summary

    # 2) attribute + PC6 joins
    planes = _join_bag(planes, paths, name)
    planes = _join_pc6(planes, paths, name)

    # 3) solar resource at the AOI centre
    lat, lon = centroid_lonlat(planes.union_all() if hasattr(planes, "union_all")
                               else planes.unary_union)
    tmy = get_tmy(lat, lon, paths.raw / "pvgis", force=force)
    solpos = solar_position(tmy.index, lat, lon)
    summary.result["resource"] = {
        "lat": round(lat, 5), "lon": round(lon, 5),
        "ghi_kwh_m2_yr": round(float(tmy["ghi"].sum()) / 1000, 1),
        "tmy_hours": int(len(tmy)),
    }

    # 4) physics yield
    planes = compute_plane_yields(planes, tmy, solpos, cfg.solar)
    yield_path = paths.processed / f"{name}_roof_yield.gpkg"
    planes.to_file(yield_path, driver="GPKG")

    # 5) per-building rollup
    buildings = _building_rollup(planes)
    bld_path = paths.processed / f"{name}_building_yield.csv"
    buildings.to_csv(bld_path, index=False)

    summary.result["yield"] = {
        "status": "ok",
        "planes": int(len(planes)),
        "buildings": int(buildings["bag_id"].nunique()),
        "total_kwp": round(float(planes["kwp"].sum()), 1),
        "total_annual_mwh": round(float(planes["annual_kwh"].sum()) / 1000, 1),
        "median_specific_yield_kwh_kwp": round(float(planes["specific_yield_kwh_kwp"].median()), 1),
        "roof_yield_gpkg": str(yield_path),
        "building_yield_csv": str(bld_path),
    }

    # 6) export map
    if make_map:
        from ..export import export_roof_geojson, write_deckgl_map

        gj = export_roof_geojson(planes, paths.processed / f"{name}_roofs.geojson")
        html = write_deckgl_map(
            planes, paths.processed / f"{name}_yield_map.html",
            title=f"Rooftop PV yield — {name}",
            subtitle=f"{len(planes):,} roof planes · "
                     f"{planes['annual_kwh'].sum()/1e6:.1f} GWh/yr technical potential",
        )
        summary.result["map"] = {"geojson": str(gj), "html": str(html)}

    # 7) validation against PVGIS
    if validate:
        try:
            from ..validate import validate_against_pvgis

            summary.result["validation"] = validate_against_pvgis(lat, lon, tmy, solpos, cfg.solar)
        except Exception as exc:  # noqa: BLE001 — validation is a bonus, never fatal
            log.warning("validation failed (%s)", exc)
            summary.result["validation"] = {"status": "error", "error": str(exc)}

    summary.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_summary(summary, paths.processed / f"{name}_yield_summary.json")
    return summary


def _building_rollup(planes):
    import pandas as pd

    df = pd.DataFrame(planes.drop(columns="geometry"))
    agg = df.groupby("bag_id").agg(
        n_planes=("plane_id", "count"),
        total_kwp=("kwp", "sum"),
        total_annual_kwh=("annual_kwh", "sum"),
        usable_area_m2=("usable_area_m2", "sum"),
        best_specific_yield=("specific_yield_kwh_kwp", "max"),
    ).reset_index()
    for opt in ("bouwjaar", "pc6"):
        if opt in df.columns:
            agg = agg.merge(df.groupby("bag_id")[opt].first().reset_index(), on="bag_id", how="left")
    agg["total_annual_kwh"] = agg["total_annual_kwh"].round(1)
    agg["total_kwp"] = agg["total_kwp"].round(3)
    return agg


def _write_summary(summary: YieldSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(summary.to_dict(), fh, indent=2, ensure_ascii=False)
