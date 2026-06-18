import json

import pytest

from rsgt.config.loader import load_config_dict
from rsgt.ingest import pipeline
from rsgt.ingest.pipeline import ALL_SOURCES, Paths, run_ingest

BBOX_AOI = {"aoi": {"name": "t", "bbox": [0, 0, 100, 100]}}


def _all_disabled():
    data = dict(BBOX_AOI)
    data["sources"] = {s: {"enabled": False} for s in ALL_SOURCES}
    return load_config_dict(data)


def test_paths_from_config(tmp_path):
    cfg = load_config_dict(BBOX_AOI)
    paths = Paths.from_config(cfg, tmp_path)
    assert paths.raw == tmp_path / "data" / "raw"
    paths.ensure()
    assert paths.processed.is_dir()


def test_run_ingest_all_disabled_writes_aoi_and_summary(tmp_path):
    cfg = _all_disabled()
    summary = run_ingest(cfg, base_dir=tmp_path)

    assert summary.aoi_source == "bbox"
    assert summary.aoi_bbox == (0.0, 0.0, 100.0, 100.0)
    assert all(r["status"] == "disabled" for r in summary.results.values())

    aoi_file = tmp_path / "data" / "interim" / "t_aoi.geojson"
    summary_file = tmp_path / "data" / "processed" / "ingest_summary.json"
    assert aoi_file.is_file()
    on_disk = json.loads(summary_file.read_text())
    assert on_disk["aoi"]["name"] == "t"


def test_run_ingest_dispatches_enabled_source(tmp_path, monkeypatch):
    called = {}

    def fake_bag3d(aoi, cfg, session, manifest, out_dir, **kw):
        called["bag3d"] = aoi.name
        return {"source": "bag3d", "status": "ok", "buildings": 7}

    monkeypatch.setattr(pipeline, "ingest_bag3d", fake_bag3d)

    data = dict(BBOX_AOI)
    data["sources"] = {s: {"enabled": s == "bag3d"} for s in ALL_SOURCES}
    cfg = load_config_dict(data)

    summary = run_ingest(cfg, base_dir=tmp_path, only=["bag3d"])
    assert called["bag3d"] == "t"
    assert summary.results["bag3d"]["buildings"] == 7


def test_unknown_source_raises(tmp_path):
    with pytest.raises(ValueError):
        run_ingest(load_config_dict(BBOX_AOI), base_dir=tmp_path, only=["bogus"])
