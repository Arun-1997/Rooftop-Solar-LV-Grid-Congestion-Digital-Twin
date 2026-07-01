import json

import geopandas as gpd
from shapely.geometry import Polygon

from rsgt.export import export_roof_geojson, write_deckgl_map


def _yield_gdf():
    # two roof planes near Oudewater (RD New)
    polys = [
        Polygon([(119050, 448800), (119060, 448800), (119060, 448810), (119050, 448810)]),
        Polygon([(119070, 448820), (119080, 448820), (119080, 448830), (119070, 448830)]),
    ]
    return gpd.GeoDataFrame(
        {
            "building_id": ["b1", "b2"],
            "bag_id": ["1", "2"],
            "plane_id": ["1::r0", "2::r0"],
            "area_m2": [100.0, 80.0],
            "usable_area_m2": [70.0, 56.0],
            "tilt_deg": [30.0, 15.0],
            "azimuth_deg": [180.0, 90.0],
            "kwp": [12.6, 10.0],
            "specific_yield_kwh_kwp": [1050.0, 900.0],
            "annual_kwh": [13230.0, 9000.0],
            "poa_kwh_m2_yr": [1300.0, 1100.0],
            "bouwjaar": [1975, 2001],
            "pc6": ["3421AB", "3421AC"],
        },
        geometry=polys,
        crs="EPSG:28992",
    )


def test_export_geojson_is_wgs84_with_fields(tmp_path):
    out = export_roof_geojson(_yield_gdf(), tmp_path / "roofs.geojson")
    data = json.loads(out.read_text())
    assert data["type"] == "FeatureCollection"
    props = data["features"][0]["properties"]
    assert "specific_yield_kwh_kwp" in props and "annual_kwh" in props
    # reprojected to WGS84 -> lon ~4.9, lat ~52
    lon, lat = data["features"][0]["geometry"]["coordinates"][0][0]
    assert 4.5 < lon < 5.5 and 51.5 < lat < 52.5


def test_deckgl_map_is_self_contained(tmp_path):
    out = write_deckgl_map(_yield_gdf(), tmp_path / "map.html", title="Test", subtitle="x")
    html = out.read_text(encoding="utf-8")
    assert "deck.gl" in html or "deck.min" in html or "deck@" in html
    assert "GeoJsonLayer" in html
    assert "specific_yield_kwh_kwp" in html  # data embedded inline
    assert "FeatureCollection" in html
