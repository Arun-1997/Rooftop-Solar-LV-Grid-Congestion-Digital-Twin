"""Live integration smoke tests against the real services.

Skipped unless ``pytest --run-network`` is passed. These verify the endpoint
shapes the offline tests mock, so a service change is caught explicitly.
"""

from __future__ import annotations

import pytest

from rsgt.config.schema import (
    AHNConfig,
    AOIConfig,
    Bag3DConfig,
    BoundaryConfig,
    HTTPConfig,
    WFSSourceConfig,
)
from rsgt.ingest.aoi import resolve_aoi
from rsgt.ingest.clients import WCSClient, WFSClient
from rsgt.ingest.download import build_session

pytestmark = pytest.mark.network

SMALL_BBOX = (119050.0, 448800.0, 119350.0, 449100.0)  # ~300 m block in Oudewater


@pytest.fixture(scope="module")
def session():
    return build_session(HTTPConfig())


def test_resolve_oudewater_boundary(session):
    aoi = resolve_aoi(AOIConfig(name="oudewater", municipality="Oudewater"),
                      BoundaryConfig(), session)
    assert aoi.source == "municipality"
    minx, miny, maxx, maxy = aoi.bbox
    assert 110_000 < minx < 125_000  # plausible RD New extent for Oudewater
    assert 440_000 < miny < 455_000


def test_3dbag_items_have_buildings(session):
    from rsgt.ingest.clients import OGCFeaturesClient

    cfg = Bag3DConfig()
    client = OGCFeaturesClient(session)
    url = f"{cfg.api_url}/collections/{cfg.collection}/items"
    params = client.bbox_params(SMALL_BBOX, cfg.bbox_crs, 5)
    page = next(client.iter_pages(url, params, max_items=5))
    assert page["features"], "expected CityJSONFeatures in the AOI"
    assert page["features"][0]["type"] == "CityJSONFeature"


def test_bag_wfs_returns_panden(session):
    feats = WFSClient(session).get_features(
        "https://service.pdok.nl/lv/bag/wfs/v2_0", "bag:pand",
        bbox=SMALL_BBOX, page_size=5, max_features=5,
    )
    assert feats
    assert "bouwjaar" in feats[0]["properties"]


def test_pc6_wfs_returns_polygons(session):
    cfg = WFSSourceConfig(
        wfs_url="https://service.pdok.nl/cbs/postcode6/2023/wfs/v1_0",
        type_names=["postcode6:postcode6"],
    )
    feats = WFSClient(session).get_features(
        cfg.wfs_url, cfg.type_names[0], bbox=SMALL_BBOX, page_size=5, max_features=5
    )
    assert feats
    assert "postcode6" in feats[0]["properties"]


def test_ahn_wcs_returns_geotiff(session):
    cfg = AHNConfig()
    data = WCSClient(session).get_coverage(cfg.wcs_url, cfg.dsm_coverage,
                                           (119100, 448900, 119200, 449000))
    assert data[:2] in (b"II", b"MM")  # TIFF little/big-endian magic
