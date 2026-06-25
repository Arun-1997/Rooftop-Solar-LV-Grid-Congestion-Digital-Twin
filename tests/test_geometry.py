import json
import math

from rsgt.config.schema import RoofConfig
from rsgt.geometry import (
    extract_roof_planes,
    filter_planes,
    newell_normal,
    normal_to_tilt_azimuth,
    polygon_area_3d,
)

# A south-facing roof rising 5 m toward the north over a 10 m run -> tilt ~26.57 deg.
SOUTH_ROOF = [(0, 0, 0), (10, 0, 0), (10, 10, 5), (0, 10, 5)]


def test_flat_square_is_horizontal():
    flat = [(0, 0, 3), (2, 0, 3), (2, 2, 3), (0, 2, 3)]
    nx, ny, nz = newell_normal(flat)
    tilt, _ = normal_to_tilt_azimuth(nx, ny, nz)
    assert tilt == 0
    assert polygon_area_3d(flat) == 4.0


def test_south_roof_tilt_and_azimuth():
    nx, ny, nz = newell_normal(SOUTH_ROOF)
    tilt, az = normal_to_tilt_azimuth(nx, ny, nz)
    assert tilt == round(math.degrees(math.atan2(5, 10)), 2) or abs(tilt - 26.57) < 0.1
    assert abs(az - 180) < 1.0  # faces south


def test_area_3d_of_tilted_plane():
    # 10 wide x sqrt(10^2+5^2) slope length
    expected = 10 * math.hypot(10, 5)
    assert abs(polygon_area_3d(SOUTH_ROOF) - expected) < 1e-6


def _write_synthetic_cityjsonseq(path):
    header = {
        "type": "CityJSON", "version": "2.0",
        "transform": {"scale": [1, 1, 1], "translate": [0, 0, 0]},
        "metadata": {"referenceSystem": "https://www.opengis.net/def/crs/EPSG/0/7415"},
        "CityObjects": {}, "vertices": [],
    }
    feature = {
        "type": "CityJSONFeature",
        "id": "NL.IMBAG.Pand.TEST123",
        "CityObjects": {
            "NL.IMBAG.Pand.TEST123": {
                "type": "Building",
                "geometry": [{
                    "type": "MultiSurface", "lod": "2.2",
                    "boundaries": [[[0, 1, 2, 3]], [[0, 1, 4]]],
                    "semantics": {
                        "surfaces": [{"type": "RoofSurface"}, {"type": "WallSurface"}],
                        "values": [0, 1],
                    },
                }],
            }
        },
        "vertices": [[0, 0, 0], [10, 0, 0], [10, 10, 5], [0, 10, 5], [0, 0, 3]],
    }
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        fh.write(json.dumps(feature) + "\n")


def test_extract_roof_planes_from_seq(tmp_path):
    p = tmp_path / "x.city.jsonl"
    _write_synthetic_cityjsonseq(p)
    gdf = extract_roof_planes(p, lod="2.2")
    assert len(gdf) == 1  # only the RoofSurface, not the wall
    row = gdf.iloc[0]
    assert row["bag_id"] == "TEST123"
    assert abs(row["tilt_deg"] - 26.57) < 0.1
    assert abs(row["azimuth_deg"] - 180) < 1.0
    assert row["geometry"].area == 100.0  # 10x10 horizontal footprint
    assert gdf.crs.to_epsg() == 28992


def test_filter_drops_small_and_north_steep():
    p_small = {"area_m2": 2.0, "tilt_deg": 30, "azimuth_deg": 180}
    p_ok = {"area_m2": 20.0, "tilt_deg": 30, "azimuth_deg": 180}
    p_north_steep = {"area_m2": 20.0, "tilt_deg": 70, "azimuth_deg": 0}
    import geopandas as gpd
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame(
        [p_small, p_ok, p_north_steep], geometry=[Point(0, 0)] * 3, crs="EPSG:28992"
    )
    kept = filter_planes(gdf, RoofConfig())
    assert len(kept) == 1
    assert kept.iloc[0]["area_m2"] == 20.0 and kept.iloc[0]["azimuth_deg"] == 180
