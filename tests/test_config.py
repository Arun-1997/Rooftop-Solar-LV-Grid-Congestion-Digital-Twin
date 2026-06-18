from pathlib import Path

import pytest
from pydantic import ValidationError

from rsgt.config import load_config, load_config_dict

CONFIGS = Path(__file__).resolve().parent.parent / "configs"


def test_load_example_configs():
    for name in ("example_small.yaml", "oudewater.yaml"):
        cfg = load_config(CONFIGS / name)
        assert cfg.aoi.name
        assert cfg.target_crs == "EPSG:28992"
        # 3D BAG must always declare the EPSG:7415 bbox CRS.
        assert "7415" in cfg.sources.bag3d.bbox_crs


def test_defaults_filled_in():
    cfg = load_config_dict({"aoi": {"name": "x", "bbox": [0, 0, 100, 100]}})
    assert cfg.sources.ahn.dsm_coverage == "dsm_05m"
    assert cfg.sources.bag.type_names == ["bag:pand"]
    assert cfg.sources.pc6.type_names == ["postcode6:postcode6"]
    assert cfg.sources.capacity.enabled is False
    assert cfg.http.max_retries == 4


def test_aoi_requires_municipality_or_bbox():
    with pytest.raises(ValidationError):
        load_config_dict({"aoi": {"name": "x"}})


def test_bbox_must_be_ordered():
    with pytest.raises(ValidationError):
        load_config_dict({"aoi": {"name": "x", "bbox": [100, 100, 0, 0]}})


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config(CONFIGS / "does_not_exist.yaml")
