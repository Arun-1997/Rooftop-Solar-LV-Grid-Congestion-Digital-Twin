"""Profile the P0 ingest artefacts into a structured set of insights.

This is the analysis core of the P0.5 *explore* step. It is split in two layers:

* **Pure summary helpers** (``numeric_summary``, ``category_counts``,
  ``summarise_buildings`` ...) operate on in-memory pandas/numpy objects and have
  no file IO, so they are cheap to unit-test.
* **A loader** (``load_artefacts``) reads the files P0 wrote (GeoPackages, GeoTIFF
  rasters, the CityJSONSeq id list, the run summary) into a :class:`LoadedData`
  bundle, and **``build_profile``** turns that bundle into an :class:`ExploreProfile`.

Rasters are read *decimated* (capped at ``max_raster_dim`` on the long side): a
0.5 m AHN coverage of a whole municipality is far too large to hold in memory, and
overview statistics do not need full resolution.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # pragma: no cover
    import geopandas as gpd

log = logging.getLogger("rsgt.explore")

BBox = tuple[float, float, float, float]


# --------------------------------------------------------------- pure summaries
def numeric_summary(values: Any) -> dict:
    """Count + min/max/mean/median/std/sum of ``values``, ignoring NaN/None."""
    arr = np.asarray(list(values), dtype="float64") if not isinstance(values, np.ndarray) else (
        values.astype("float64")
    )
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"count": 0}
    return {
        "count": int(arr.size),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "std": float(np.std(arr)),
        "sum": float(np.sum(arr)),
    }


def category_counts(values: Any, *, top: int = 12) -> dict[str, int]:
    """Value counts as a plain dict; everything past ``top`` folds into ``(other)``."""
    s = pd.Series(list(values)).dropna().astype(str)
    vc = s.value_counts()
    out = {str(k): int(v) for k, v in vc.head(top).items()}
    if len(vc) > top:
        out["(other)"] = int(vc.iloc[top:].sum())
    return out


def _decade_counts(years: pd.Series) -> dict[str, int]:
    y = pd.to_numeric(years, errors="coerce").dropna()
    y = y[(y > 1000) & (y < 2100)]
    if y.empty:
        return {}
    decades = (y // 10 * 10).astype(int)
    return {str(int(k)): int(v) for k, v in decades.value_counts().sort_index().items()}


def summarise_buildings(gdf: gpd.GeoDataFrame) -> dict:
    """Footprint-area, construction-year, status and use-function stats for BAG panden."""
    n = int(len(gdf))
    out: dict[str, Any] = {"status": "ok", "count": n}
    if n == 0:
        out["status"] = "empty"
        return out
    if getattr(gdf, "geometry", None) is not None and not gdf.geometry.isna().all():
        out["footprint_area_m2"] = numeric_summary(gdf.geometry.area.to_numpy())
    if "bouwjaar" in gdf.columns:
        years = pd.to_numeric(gdf["bouwjaar"], errors="coerce")
        out["construction_year"] = numeric_summary(years.to_numpy())
        out["construction_decade_counts"] = _decade_counts(years)
    if "status" in gdf.columns:
        out["pand_status_counts"] = category_counts(gdf["status"])
    for col in ("gebruiksdoel", "gebruiksdoelen", "gebruiksdoelVerblijfsobject"):
        if col in gdf.columns:
            out["use_function_counts"] = category_counts(gdf[col])
            break
    return out


def summarise_pc6(gdf: gpd.GeoDataFrame) -> dict:
    """Count + area stats for the PC6 aggregation polygons."""
    n = int(len(gdf))
    out: dict[str, Any] = {"status": "ok", "count": n}
    if n == 0:
        out["status"] = "empty"
        return out
    if getattr(gdf, "geometry", None) is not None and not gdf.geometry.isna().all():
        out["area_m2"] = numeric_summary(gdf.geometry.area.to_numpy())
    for col in ("postcode6", "postcode", "pc6", "PC6"):
        if col in gdf.columns:
            out["unique_codes"] = int(gdf[col].nunique())
            break
    return out


def raster_array_stats(
    array: np.ndarray, *, res_m: float | None = None, nodata: float | None = None
) -> dict:
    """Coverage + value distribution for a (decimated) raster band."""
    a = np.asarray(array, dtype="float64")
    if nodata is not None:
        a = np.where(a == nodata, np.nan, a)
    valid = a[np.isfinite(a)]
    out: dict[str, Any] = {
        "shape": [int(s) for s in array.shape],
        "valid_fraction": float(valid.size / a.size) if a.size else 0.0,
    }
    if res_m is not None:
        out["resolution_m"] = float(res_m)
    if valid.size:
        out["value"] = numeric_summary(valid)
    return out


def object_height_stats(
    dsm: np.ndarray, dtm: np.ndarray, *, nodata: float | None = None, min_height_m: float = 2.0
) -> dict:
    """Above-ground object height (DSM - DTM) stats; arrays must share a shape."""
    d = np.asarray(dsm, dtype="float64")
    t = np.asarray(dtm, dtype="float64")
    if d.shape != t.shape:
        return {"status": "shape-mismatch", "dsm_shape": list(d.shape), "dtm_shape": list(t.shape)}
    if nodata is not None:
        d = np.where(d == nodata, np.nan, d)
        t = np.where(t == nodata, np.nan, t)
    h = d - t
    h = h[np.isfinite(h)]
    if h.size == 0:
        return {"status": "empty"}
    return {
        "status": "ok",
        "height_m": numeric_summary(h),
        f"above_{min_height_m:g}m_fraction": float(np.count_nonzero(h >= min_height_m) / h.size),
    }


# ------------------------------------------------------------------ loaded data
@dataclass
class RasterData:
    array: np.ndarray
    res_m: float
    native_res_m: float
    native_shape: tuple[int, int]
    nodata: float | None
    bounds: BBox


@dataclass
class LoadedData:
    """In-memory bundle of the P0 artefacts found for one AOI."""

    aoi_name: str
    aoi: gpd.GeoDataFrame | None = None
    buildings: gpd.GeoDataFrame | None = None
    pc6: gpd.GeoDataFrame | None = None
    capacity: dict[str, gpd.GeoDataFrame] = field(default_factory=dict)
    dsm: RasterData | None = None
    dtm: RasterData | None = None
    bag3d_count: int | None = None
    ingest_summary: dict | None = None
    manifest: dict | None = None
    load_status: dict[str, str] = field(default_factory=dict)


def _first(paths: list[Path]) -> Path | None:
    return paths[0] if paths else None


def _read_raster(path: Path, max_dim: int) -> RasterData:
    import rasterio

    with rasterio.open(path) as ds:
        h, w = ds.height, ds.width
        scale = max(1, math.ceil(max(h, w) / max_dim))
        oh, ow = max(1, h // scale), max(1, w // scale)
        arr = ds.read(1, out_shape=(oh, ow))
        b = ds.bounds
        native_res = float(ds.res[0])
        return RasterData(
            array=arr,
            res_m=native_res * (w / ow) if ow else native_res,
            native_res_m=native_res,
            native_shape=(h, w),
            nodata=ds.nodata,
            bounds=(b.left, b.bottom, b.right, b.top),
        )


def _read_raster_like(path: Path, ref: RasterData) -> RasterData:
    """Read ``path`` decimated to ``ref``'s shape so DSM/DTM arrays align."""
    import rasterio

    oh, ow = ref.array.shape
    with rasterio.open(path) as ds:
        arr = ds.read(1, out_shape=(oh, ow))
        b = ds.bounds
        return RasterData(
            array=arr,
            res_m=ref.res_m,
            native_res_m=float(ds.res[0]),
            native_shape=(ds.height, ds.width),
            nodata=ds.nodata,
            bounds=(b.left, b.bottom, b.right, b.top),
        )


def load_artefacts(raw: Path, interim: Path, processed: Path, aoi_name: str, *, max_raster_dim: int = 1200) -> LoadedData:
    """Locate and load whatever P0 produced for ``aoi_name``. Missing/broken
    artefacts are recorded in ``load_status`` rather than raising."""
    import json

    import geopandas as gpd

    data = LoadedData(aoi_name=aoi_name)

    def _attempt(name: str, fn) -> None:
        try:
            fn()
            data.load_status.setdefault(name, "ok")
        except Exception as exc:  # noqa: BLE001 — one bad artefact shouldn't sink the report
            log.warning("explore: could not load %s (%s)", name, exc)
            data.load_status[name] = f"error: {exc}"

    def _load_aoi() -> None:
        p = interim / f"{aoi_name}_aoi.geojson"
        if not p.is_file():
            data.load_status["aoi"] = "missing"
            return
        data.aoi = gpd.read_file(p)

    def _load_buildings() -> None:
        d = raw / "bag"
        p = _first(sorted(d.glob(f"{aoi_name}_*pand*.gpkg"))) or _first(sorted(d.glob("*.gpkg")))
        if p is None:
            data.load_status["buildings"] = "missing"
            return
        data.buildings = gpd.read_file(p)

    def _load_pc6() -> None:
        p = _first(sorted((raw / "pc6").glob("*.gpkg")))
        if p is None:
            data.load_status["pc6"] = "missing"
            return
        data.pc6 = gpd.read_file(p)

    def _load_capacity() -> None:
        files = sorted((raw / "capacity").glob("*.gpkg"))
        if not files:
            data.load_status["capacity"] = "missing"
            return
        for p in files:
            kind = p.stem.split("_capacity_")[-1]
            data.capacity[kind] = gpd.read_file(p)

    def _load_rasters() -> None:
        dsm_p = raw / "ahn" / f"{aoi_name}_dsm.tif"
        dtm_p = raw / "ahn" / f"{aoi_name}_dtm.tif"
        if dsm_p.is_file():
            data.dsm = _read_raster(dsm_p, max_raster_dim)
        if dtm_p.is_file():
            data.dtm = (
                _read_raster_like(dtm_p, data.dsm)
                if data.dsm is not None
                else _read_raster(dtm_p, max_raster_dim)
            )
        if data.dsm is None and data.dtm is None:
            data.load_status["ahn"] = "missing"

    def _load_bag3d() -> None:
        ids = raw / "bag3d" / f"{aoi_name}_buildings.txt"
        if ids.is_file():
            with ids.open("r", encoding="utf-8") as fh:
                data.bag3d_count = sum(1 for line in fh if line.strip())
        else:
            data.load_status["bag3d"] = "missing"

    def _load_provenance() -> None:
        s = processed / "ingest_summary.json"
        m = raw / "manifest.json"
        if s.is_file():
            data.ingest_summary = json.loads(s.read_text(encoding="utf-8"))
        if m.is_file():
            data.manifest = json.loads(m.read_text(encoding="utf-8"))

    _attempt("aoi", _load_aoi)
    _attempt("buildings", _load_buildings)
    _attempt("pc6", _load_pc6)
    _attempt("capacity", _load_capacity)
    _attempt("ahn", _load_rasters)
    _attempt("bag3d", _load_bag3d)
    _attempt("provenance", _load_provenance)
    return data


# --------------------------------------------------------------------- profile
@dataclass
class ExploreProfile:
    aoi_name: str
    generated_at: str
    headline: list[str] = field(default_factory=list)
    aoi: dict = field(default_factory=dict)
    buildings: dict = field(default_factory=dict)
    bag3d: dict = field(default_factory=dict)
    pc6: dict = field(default_factory=dict)
    ahn: dict = field(default_factory=dict)
    capacity: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    load_status: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "aoi_name": self.aoi_name,
            "generated_at": self.generated_at,
            "headline": self.headline,
            "aoi": self.aoi,
            "buildings": self.buildings,
            "bag3d": self.bag3d,
            "pc6": self.pc6,
            "ahn": self.ahn,
            "capacity": self.capacity,
            "provenance": self.provenance,
            "load_status": self.load_status,
        }


def _aoi_section(data: LoadedData) -> dict:
    if data.aoi is None or len(data.aoi) == 0:
        return {"status": data.load_status.get("aoi", "missing")}
    g = data.aoi
    minx, miny, maxx, maxy = (float(v) for v in g.total_bounds)
    out = {
        "status": "ok",
        "crs": str(g.crs),
        "bbox_rd": [round(minx, 1), round(miny, 1), round(maxx, 1), round(maxy, 1)],
        "width_m": round(maxx - minx, 1),
        "height_m": round(maxy - miny, 1),
        "area_km2": round(float(g.geometry.area.sum()) / 1e6, 4),
    }
    if "source" in g.columns:
        out["source"] = str(g["source"].iloc[0])
    return out


def _ahn_section(data: LoadedData) -> dict:
    if data.dsm is None and data.dtm is None:
        return {"status": data.load_status.get("ahn", "missing")}
    out: dict[str, Any] = {"status": "ok"}
    if data.dsm is not None:
        out["dsm"] = raster_array_stats(
            data.dsm.array, res_m=data.dsm.res_m, nodata=data.dsm.nodata
        ) | {"native_resolution_m": data.dsm.native_res_m}
    if data.dtm is not None:
        out["dtm"] = raster_array_stats(
            data.dtm.array, res_m=data.dtm.res_m, nodata=data.dtm.nodata
        ) | {"native_resolution_m": data.dtm.native_res_m}
    if data.dsm is not None and data.dtm is not None:
        nodata = data.dsm.nodata if data.dsm.nodata is not None else data.dtm.nodata
        out["object_height"] = object_height_stats(data.dsm.array, data.dtm.array, nodata=nodata)
    return out


def _provenance_section(data: LoadedData) -> dict:
    out: dict[str, Any] = {}
    if data.ingest_summary:
        results = data.ingest_summary.get("results", {})
        out["source_status"] = {k: v.get("status") for k, v in results.items()}
        out["started_at"] = data.ingest_summary.get("started_at")
        out["finished_at"] = data.ingest_summary.get("finished_at")
    if data.manifest:
        entries = data.manifest.get("entries", {})
        out["downloads"] = len(entries)
        out["downloaded_bytes"] = int(sum(e.get("bytes", 0) for e in entries.values()))
    return out


def _headline(profile: ExploreProfile) -> list[str]:
    """A few human-readable take-aways for the top of the report / the script."""
    lines: list[str] = []
    aoi = profile.aoi
    if aoi.get("status") == "ok":
        lines.append(f"AOI '{profile.aoi_name}' covers {aoi['area_km2']} km² ({aoi.get('source', '?')}).")
    b = profile.buildings
    if b.get("status") == "ok":
        msg = f"{b['count']:,} BAG buildings"
        area = b.get("footprint_area_m2", {})
        if area.get("count"):
            msg += f"; median footprint {area['median']:.0f} m²"
        yr = b.get("construction_year", {})
        if yr.get("count"):
            msg += f"; built {int(yr['min'])}–{int(yr['max'])}"
        lines.append(msg + ".")
    if profile.bag3d.get("buildings") is not None:
        lines.append(f"{profile.bag3d['buildings']:,} 3D BAG building models available for roof extraction.")
    if profile.pc6.get("status") == "ok":
        lines.append(f"{profile.pc6['count']:,} PC6 aggregation polygons.")
    oh = profile.ahn.get("object_height", {})
    if oh.get("status") == "ok":
        h = oh.get("height_m", {})
        frac_key = next((k for k in oh if k.startswith("above_")), None)
        extra = f"; {oh[frac_key] * 100:.0f}% of cells >2 m above ground" if frac_key else ""
        if h.get("count"):
            lines.append(f"AHN object height: median {h['median']:.1f} m, max {h['max']:.1f} m{extra}.")
    return lines


def build_profile(data: LoadedData) -> ExploreProfile:
    """Turn a :class:`LoadedData` bundle into a structured :class:`ExploreProfile`."""
    profile = ExploreProfile(
        aoi_name=data.aoi_name,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        load_status=dict(data.load_status),
    )
    profile.aoi = _aoi_section(data)
    profile.buildings = (
        summarise_buildings(data.buildings)
        if data.buildings is not None
        else {"status": data.load_status.get("buildings", "missing")}
    )
    profile.bag3d = (
        {"status": "ok", "buildings": int(data.bag3d_count)}
        if data.bag3d_count is not None
        else {"status": data.load_status.get("bag3d", "missing")}
    )
    profile.pc6 = (
        summarise_pc6(data.pc6)
        if data.pc6 is not None
        else {"status": data.load_status.get("pc6", "missing")}
    )
    profile.ahn = _ahn_section(data)
    if data.capacity:
        profile.capacity = {
            "status": "ok",
            "layers": {kind: int(len(gdf)) for kind, gdf in data.capacity.items()},
        }
    else:
        profile.capacity = {"status": data.load_status.get("capacity", "missing")}
    profile.provenance = _provenance_section(data)
    profile.headline = _headline(profile)
    return profile
