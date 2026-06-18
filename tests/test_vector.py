import geopandas as gpd
from shapely.geometry import Point

from rsgt.geo.crs import RD_NEW, bbox_polygon
from rsgt.ingest.aoi import AreaOfInterest
from rsgt.ingest.vector import clip_to_aoi, save_vector


def _aoi():
    return AreaOfInterest(name="t", geometry=bbox_polygon((0, 0, 10, 10)), bbox=(0, 0, 10, 10))


def test_clip_keeps_only_intersecting():
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2, 3]},
        geometry=[Point(5, 5), Point(50, 50), Point(1, 1)],
        crs=RD_NEW,
    )
    out = clip_to_aoi(gdf, _aoi())
    assert sorted(out["id"]) == [1, 3]


def test_save_nonempty_gpkg(tmp_path):
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(5, 5)], crs=RD_NEW)
    out = save_vector(gdf, tmp_path / "layer")
    assert out.suffix == ".gpkg"
    reloaded = gpd.read_file(out)
    assert len(reloaded) == 1


def test_save_empty_geojson(tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[], crs=RD_NEW)
    out = save_vector(gdf, tmp_path / "empty")
    assert out.suffix == ".geojson"
    assert "FeatureCollection" in out.read_text()
