import json

import pytest

from conftest import FakeResponse, FakeSession
from rsgt.config.schema import AOIConfig, BoundaryConfig
from rsgt.ingest.aoi import resolve_aoi

BOUNDARY = BoundaryConfig()


def _raise_session():
    def handler(url, params):  # pragma: no cover - should never be called
        raise AssertionError("network used for a bbox-only AOI")

    return FakeSession(handler)


def _poly_session(coords):
    def handler(url, params):
        return FakeResponse(
            json_data={
                "features": [{"type": "Feature", "properties": {},
                              "geometry": {"type": "Polygon", "coordinates": [coords]}}],
                "links": [],
            }
        )

    return FakeSession(handler)


def test_bbox_only_no_network():
    cfg = AOIConfig(name="b", bbox=(0, 0, 100, 100))
    aoi = resolve_aoi(cfg, BOUNDARY, _raise_session())
    assert aoi.source == "bbox"
    assert aoi.bbox == (0.0, 0.0, 100.0, 100.0)
    assert aoi.geometry.area == pytest.approx(10000)


def test_bbox_buffer_expands():
    cfg = AOIConfig(name="b", bbox=(0, 0, 100, 100), buffer_m=10)
    aoi = resolve_aoi(cfg, BOUNDARY, _raise_session())
    assert aoi.bbox[0] == -10 and aoi.bbox[2] == 110


def test_municipality_resolution():
    square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    cfg = AOIConfig(name="m", municipality="Testtown")
    aoi = resolve_aoi(cfg, BOUNDARY, _poly_session(square))
    assert aoi.source == "municipality"
    assert aoi.bbox == (0.0, 0.0, 10.0, 10.0)


def test_municipality_with_bbox_clip():
    square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    cfg = AOIConfig(name="m", municipality="Testtown", bbox=(2, 2, 6, 6))
    aoi = resolve_aoi(cfg, BOUNDARY, _poly_session(square))
    assert aoi.source == "municipality+bbox"
    assert aoi.bbox == (2.0, 2.0, 6.0, 6.0)


def test_municipality_failure_falls_back_to_bbox():
    def handler(url, params):
        return FakeResponse(json_data={"features": [], "links": []})  # no match

    cfg = AOIConfig(name="m", municipality="Nowhere", bbox=(1, 1, 5, 5))
    aoi = resolve_aoi(cfg, BOUNDARY, FakeSession(handler))
    assert aoi.source == "bbox"
    assert aoi.bbox == (1.0, 1.0, 5.0, 5.0)


def test_aoi_save_writes_geojson(tmp_path):
    cfg = AOIConfig(name="b", bbox=(0, 0, 100, 100))
    aoi = resolve_aoi(cfg, BOUNDARY, _raise_session())
    out = aoi.save(tmp_path / "aoi.geojson")
    data = json.loads(out.read_text())
    assert data["type"] == "FeatureCollection"
    assert data["features"][0]["geometry"]["type"] == "Polygon"
