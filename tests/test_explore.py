"""Offline tests for the P0.5 explore step.

The pure summary helpers are tested directly; the end-to-end ``run_explore`` is
tested against a tiny synthetic ``data/`` tree written to ``tmp_path`` (no network).
"""

import json

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from rsgt.config.loader import load_config_dict
from rsgt.explore import run_explore
from rsgt.explore.profile import (
    category_counts,
    numeric_summary,
    object_height_stats,
    raster_array_stats,
    summarise_buildings,
    summarise_pc6,
)

RD_NEW = "EPSG:28992"


# --------------------------------------------------------------- pure helpers
def test_numeric_summary_ignores_nan():
    s = numeric_summary([1.0, 2.0, 3.0, np.nan, None and 0])
    assert s["count"] == 3
    assert s["min"] == 1.0 and s["max"] == 3.0
    assert s["mean"] == 2.0 and s["median"] == 2.0


def test_numeric_summary_empty():
    assert numeric_summary([np.nan, np.nan])["count"] == 0


def test_category_counts_folds_other():
    vals = ["a"] * 5 + ["b"] * 3 + ["c", "d", "e"]
    out = category_counts(vals, top=2)
    assert out["a"] == 5 and out["b"] == 3
    assert out["(other)"] == 3  # c + d + e


def test_summarise_buildings():
    gdf = gpd.GeoDataFrame(
        {
            "bouwjaar": [1905, 1965, 1968, 2001, None],
            "status": ["in gebruik", "in gebruik", "in gebruik", "sloop", "in gebruik"],
        },
        geometry=[box(0, 0, 10, 10), box(0, 0, 5, 5), box(0, 0, 20, 5), box(0, 0, 8, 8), box(0, 0, 4, 4)],
        crs=RD_NEW,
    )
    out = summarise_buildings(gdf)
    assert out["count"] == 5
    assert out["footprint_area_m2"]["count"] == 5
    assert out["construction_year"]["count"] == 4  # the None is dropped
    assert out["construction_decade_counts"]["1960"] == 2  # 1965 + 1968
    assert out["pand_status_counts"]["in gebruik"] == 4


def test_summarise_buildings_empty():
    gdf = gpd.GeoDataFrame(geometry=[], crs=RD_NEW)
    assert summarise_buildings(gdf)["status"] == "empty"


def test_summarise_pc6_counts_codes():
    gdf = gpd.GeoDataFrame(
        {"postcode6": ["3421AA", "3421AB"]},
        geometry=[box(0, 0, 100, 100), box(100, 0, 200, 100)],
        crs=RD_NEW,
    )
    out = summarise_pc6(gdf)
    assert out["count"] == 2 and out["unique_codes"] == 2
    assert out["area_m2"]["sum"] == pytest.approx(20000.0)


def test_raster_array_stats_masks_nodata():
    a = np.array([[1.0, 2.0], [3.0, -9999.0]])
    out = raster_array_stats(a, res_m=0.5, nodata=-9999.0)
    assert out["shape"] == [2, 2]
    assert out["valid_fraction"] == pytest.approx(0.75)
    assert out["value"]["max"] == 3.0
    assert out["resolution_m"] == 0.5


def test_object_height_stats():
    dtm = np.zeros((4, 4))
    dsm = np.full((4, 4), 5.0)
    dsm[0, 0] = 0.0  # one ground cell
    out = object_height_stats(dsm, dtm, min_height_m=2.0)
    assert out["status"] == "ok"
    assert out["height_m"]["max"] == 5.0
    assert out["above_2m_fraction"] == pytest.approx(15 / 16)


def test_object_height_shape_mismatch():
    out = object_height_stats(np.zeros((2, 2)), np.zeros((3, 3)))
    assert out["status"] == "shape-mismatch"


# ------------------------------------------------------------- end-to-end run
def _write_synthetic_ingest(base, name="t"):
    """Write a minimal P0-style data/ tree under ``base`` and return the config."""
    import rasterio
    from rasterio.transform import from_bounds

    root = base / "data"
    raw, interim, processed = root / "raw", root / "interim", root / "processed"
    for d in (raw / "bag", raw / "pc6", raw / "ahn", raw / "bag3d", interim, processed):
        d.mkdir(parents=True, exist_ok=True)

    bbox = (0.0, 0.0, 100.0, 100.0)

    # AOI
    aoi = gpd.GeoDataFrame({"name": [name], "source": ["bbox"]}, geometry=[box(*bbox)], crs=RD_NEW)
    aoi.to_file(interim / f"{name}_aoi.geojson", driver="GeoJSON")

    # BAG panden
    bag = gpd.GeoDataFrame(
        {"bouwjaar": [1920, 1975, 2010], "status": ["in gebruik"] * 3},
        geometry=[box(10, 10, 20, 20), box(30, 30, 45, 40), box(50, 50, 60, 70)],
        crs=RD_NEW,
    )
    bag.to_file(raw / "bag" / f"{name}_bag_pand.gpkg", driver="GPKG")

    # PC6
    pc6 = gpd.GeoDataFrame(
        {"postcode6": ["1000AA", "1000AB"]},
        geometry=[box(0, 0, 50, 100), box(50, 0, 100, 100)],
        crs=RD_NEW,
    )
    pc6.to_file(raw / "pc6" / f"{name}_postcode6_postcode6.gpkg", driver="GPKG")

    # AHN DSM/DTM
    h = w = 20
    transform = from_bounds(*bbox, w, h)
    dtm = np.zeros((h, w), dtype="float32")
    dsm = dtm + 4.0
    profile = dict(driver="GTiff", height=h, width=w, count=1, dtype="float32",
                   crs=RD_NEW, transform=transform, nodata=-9999.0)
    for fname, arr in ((f"{name}_dsm.tif", dsm), (f"{name}_dtm.tif", dtm)):
        with rasterio.open(raw / "ahn" / fname, "w", **profile) as dst:
            dst.write(arr, 1)

    # 3D BAG id list
    (raw / "bag3d" / f"{name}_buildings.txt").write_text("a\nb\nc\nd\n", encoding="utf-8")

    # provenance
    (processed / "ingest_summary.json").write_text(
        json.dumps({"aoi": {"name": name}, "results": {"bag": {"status": "ok"}},
                    "started_at": "x", "finished_at": "y"}), encoding="utf-8")
    (raw / "manifest.json").write_text(
        json.dumps({"entries": {"k": {"bytes": 123}}}), encoding="utf-8")

    return load_config_dict({"aoi": {"name": name, "bbox": list(bbox)}})


def test_run_explore_no_plots_writes_insights(tmp_path):
    cfg = _write_synthetic_ingest(tmp_path)
    profile = run_explore(cfg, base_dir=tmp_path, make_plots=False)

    assert profile.buildings["count"] == 3
    assert profile.bag3d["buildings"] == 4
    assert profile.pc6["count"] == 2
    assert profile.ahn["object_height"]["height_m"]["max"] == pytest.approx(4.0)
    assert profile.aoi["area_km2"] == pytest.approx(0.01)  # 100m x 100m
    assert profile.headline  # at least one take-away
    # everything we wrote loaded cleanly; capacity was deliberately not ingested
    for key in ("aoi", "buildings", "pc6", "ahn", "bag3d", "provenance"):
        assert profile.load_status[key] == "ok", profile.load_status
    assert profile.capacity["status"] == "missing"

    out = tmp_path / "data" / "processed" / "explore"
    on_disk = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    assert on_disk["buildings"]["count"] == 3
    assert (out / "report.html").is_file()


def test_run_explore_with_plots(tmp_path):
    pytest.importorskip("matplotlib")
    cfg = _write_synthetic_ingest(tmp_path)
    run_explore(cfg, base_dir=tmp_path, make_plots=True)

    fig_dir = tmp_path / "data" / "processed" / "explore" / "figures"
    produced = {p.name for p in fig_dir.glob("*.png")}
    assert {"overview.png", "construction_years.png", "footprint_areas.png",
            "ahn_dsm.png", "ahn_object_height.png"} <= produced

    # report embeds the figures inline (base64), so it must be self-contained
    html = (tmp_path / "data" / "processed" / "explore" / "report.html").read_text(encoding="utf-8")
    assert "data:image/png;base64," in html


def test_run_explore_missing_artefacts_is_graceful(tmp_path):
    (tmp_path / "data" / "processed").mkdir(parents=True)
    cfg = load_config_dict({"aoi": {"name": "empty", "bbox": [0, 0, 10, 10]}})
    profile = run_explore(cfg, base_dir=tmp_path, make_plots=False, make_map=False)
    assert profile.buildings["status"] == "missing"
    assert (tmp_path / "data" / "processed" / "explore" / "insights.json").is_file()


# ----------------------------------------------------------- interactive map
def test_build_map_returns_folium_map(tmp_path):
    folium = pytest.importorskip("folium")
    from rsgt.explore.interactive import build_map
    from rsgt.explore.profile import load_artefacts

    _write_synthetic_ingest(tmp_path)
    data = load_artefacts(
        tmp_path / "data" / "raw", tmp_path / "data" / "interim",
        tmp_path / "data" / "processed", "t",
    )
    m = build_map(data)
    assert isinstance(m, folium.Map)


def test_build_map_none_without_spatial_data():
    pytest.importorskip("folium")
    from rsgt.explore.interactive import build_map
    from rsgt.explore.profile import LoadedData

    assert build_map(LoadedData(aoi_name="empty")) is None


def test_run_explore_writes_interactive_map(tmp_path):
    pytest.importorskip("folium")
    cfg = _write_synthetic_ingest(tmp_path)
    run_explore(cfg, base_dir=tmp_path, make_plots=False, make_map=True)

    out = tmp_path / "data" / "processed" / "explore"
    map_html = out / "map.html"
    assert map_html.is_file()
    assert "leaflet" in map_html.read_text(encoding="utf-8").lower()
    # the report should link to the map
    assert 'href="map.html"' in (out / "report.html").read_text(encoding="utf-8")
