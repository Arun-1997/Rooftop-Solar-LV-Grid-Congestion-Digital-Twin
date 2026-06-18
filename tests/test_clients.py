from conftest import FakeResponse, FakeSession
from rsgt.ingest.clients import (
    ArcGISFeatureServiceClient,
    OGCFeaturesClient,
    WCSClient,
    WFSClient,
    features_to_gdf,
)


def _feat(i):
    return {"type": "Feature", "properties": {"id": i}, "geometry": {"type": "Point", "coordinates": [i, i]}}


# ----------------------------------------------------------------------- WFS
def test_wfs_pagination_and_bbox():
    def handler(url, params):
        start = int(params["startIndex"])
        assert params["bbox"] == "0,0,10,10,EPSG:28992"
        if start == 0:
            page = [_feat(0), _feat(1)]
        elif start == 2:
            page = [_feat(2)]
        else:
            page = []
        return FakeResponse(json_data={"features": page, "numberReturned": len(page)})

    client = WFSClient(FakeSession(handler))
    feats = client.get_features(
        "http://wfs", "bag:pand", bbox=(0, 0, 10, 10), page_size=2
    )
    assert [f["properties"]["id"] for f in feats] == [0, 1, 2]


def test_wfs_max_features_cap():
    def handler(url, params):
        return FakeResponse(json_data={"features": [_feat(0), _feat(1)], "numberReturned": 2})

    client = WFSClient(FakeSession(handler))
    feats = client.get_features("http://wfs", "t", page_size=2, max_features=1)
    assert len(feats) == 1


# ----------------------------------------------------------- OGC API Features
def test_ogc_follows_next_links():
    def handler(url, params):
        if "offset" not in url:
            return FakeResponse(
                json_data={
                    "features": [_feat(0)],
                    "numberReturned": 1,
                    "links": [{"rel": "next", "href": "http://api/items?offset=1"}],
                }
            )
        # second page: no next link -> stop
        assert params is None  # next links are fully-qualified
        return FakeResponse(json_data={"features": [_feat(1)], "numberReturned": 1, "links": []})

    sess = FakeSession(handler)
    client = OGCFeaturesClient(sess)
    feats = client.get_geojson_features("http://api/items", {"bbox": "0,0,1,1"})
    assert [f["properties"]["id"] for f in feats] == [0, 1]
    assert len(sess.calls) == 2


def test_ogc_bbox_params():
    client = OGCFeaturesClient(FakeSession(lambda u, p: FakeResponse(json_data={})))
    params = client.bbox_params((1, 2, 3, 4), "http://crs/7415", 200)
    assert params == {"bbox": "1,2,3,4", "bbox-crs": "http://crs/7415", "limit": 200}


# --------------------------------------------------------- ArcGIS FeatureServer
def test_arcgis_pagination_uses_exceeded_flag():
    def handler(url, params):
        offset = int(params["resultOffset"])
        assert url.endswith("/query")
        if offset == 0:
            return FakeResponse(
                json_data={"features": [_feat(0), _feat(1)], "exceededTransferLimit": True}
            )
        return FakeResponse(json_data={"features": [_feat(2)], "exceededTransferLimit": False})

    client = ArcGISFeatureServiceClient(FakeSession(handler))
    feats = client.query_layer("http://arc/FeatureServer/3", bbox=(0, 0, 9, 9), page_size=2)
    assert [f["properties"]["id"] for f in feats] == [0, 1, 2]


# ----------------------------------------------------------------------- WCS
def test_wcs_get_coverage_returns_bytes():
    captured = {}

    def handler(url, params):
        captured.update(params)
        return FakeResponse(content=b"II*\x00tiffbytes", headers={"content-type": "image/tiff"})

    client = WCSClient(FakeSession(handler))
    data = client.get_coverage("http://wcs", "dsm_05m", (0, 0, 100, 200))
    assert data.startswith(b"II*")
    assert captured["subset"] == ["x(0,100)", "y(0,200)"]
    assert "subsettingCrs" not in captured  # not sent unless requested


def test_wcs_rejects_non_raster():
    def handler(url, params):
        return FakeResponse(
            content=b"<ExceptionReport/>", headers={"content-type": "text/xml"}, text="<error/>"
        )

    client = WCSClient(FakeSession(handler))
    try:
        client.get_coverage("http://wcs", "dsm_05m", (0, 0, 1, 1))
    except RuntimeError as e:
        assert "not a coverage" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


# ------------------------------------------------------------------ to gdf
def test_features_to_gdf_sets_crs():
    gdf = features_to_gdf([_feat(0), _feat(1)], "EPSG:28992")
    assert len(gdf) == 2
    assert gdf.crs.to_epsg() == 28992
    empty = features_to_gdf([], "EPSG:28992")
    assert len(empty) == 0
    assert empty.crs.to_epsg() == 28992
