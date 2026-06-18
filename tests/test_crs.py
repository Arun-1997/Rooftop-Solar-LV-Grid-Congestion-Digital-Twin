from rsgt.geo.crs import (
    RD_NEW,
    WGS84,
    bbox_polygon,
    buffer_bbox,
    epsg_uri,
    reproject_bbox,
    tile_bbox,
)

OUDEWATER_BBOX = (114607.0, 444338.0, 123397.0, 452922.0)


def test_epsg_uri():
    assert epsg_uri("EPSG:28992") == "http://www.opengis.net/def/crs/EPSG/0/28992"
    assert epsg_uri("EPSG:7415").endswith("/7415")


def test_reproject_bbox_roundtrip_contains_original():
    wgs = reproject_bbox(OUDEWATER_BBOX, RD_NEW, WGS84)
    # Netherlands longitudes ~3.3-7.2, latitudes ~50.7-53.6
    assert 3.0 < wgs[0] < 7.5 and 50.0 < wgs[1] < 54.0
    back = reproject_bbox(wgs, WGS84, RD_NEW)
    # Densified reprojection must enclose the original rectangle.
    assert back[0] <= OUDEWATER_BBOX[0] + 1
    assert back[1] <= OUDEWATER_BBOX[1] + 1
    assert back[2] >= OUDEWATER_BBOX[2] - 1
    assert back[3] >= OUDEWATER_BBOX[3] - 1


def test_reproject_bbox_identity():
    assert reproject_bbox(OUDEWATER_BBOX, RD_NEW, RD_NEW) == OUDEWATER_BBOX


def test_tile_bbox_grid():
    tiles = tile_bbox((0, 0, 1000, 1000), 400)
    assert len(tiles) == 9  # ceil(1000/400) == 3 per axis
    # Tiles cover the whole box and stay within it.
    assert min(t[0] for t in tiles) == 0
    assert max(t[2] for t in tiles) == 1000
    assert all(t[2] - t[0] <= 400 + 1e-9 for t in tiles)


def test_tile_bbox_single():
    assert tile_bbox((0, 0, 300, 300), 1000) == [(0, 0, 300, 300)]


def test_buffer_and_polygon():
    assert buffer_bbox((10, 20, 30, 40), 5) == (5, 15, 35, 45)
    poly = bbox_polygon((0, 0, 2, 2))
    assert poly.area == 4
