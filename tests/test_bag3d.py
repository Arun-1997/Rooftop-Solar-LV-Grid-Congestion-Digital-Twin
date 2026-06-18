import json

from conftest import FakeResponse, FakeSession
from rsgt.config.schema import Bag3DConfig
from rsgt.geo.crs import bbox_polygon
from rsgt.ingest.aoi import AreaOfInterest
from rsgt.ingest.bag3d import _rewrite_feature, ingest_bag3d, requantize_vertex
from rsgt.ingest.manifest import DownloadManifest

A = {"scale": [0.001, 0.001, 0.001], "translate": [0.0, 0.0, 0.0]}
B = {"scale": [0.001, 0.001, 0.001], "translate": [1.0, 2.0, 0.0]}


def _real(v, t):
    return tuple(v[i] * t["scale"][i] + t["translate"][i] for i in range(3))


def test_requantize_preserves_real_coordinates():
    v = [500, 500, 0]
    out = requantize_vertex(v, B, A)
    assert _real(out, A) == _real(v, B)  # exact for matching 0.001 scale


def test_rewrite_feature_noop_when_same_transform():
    feat = {"id": "F", "vertices": [[1, 2, 3]]}
    assert _rewrite_feature(feat, A, A) is feat


def _city_feature(fid, verts):
    return {"type": "CityJSONFeature", "id": fid, "CityObjects": {}, "vertices": verts}


def test_ingest_bag3d_merges_pages_to_one_transform(tmp_path):
    def handler(url, params):
        if "offset" not in (url + json.dumps(params or {})):
            return FakeResponse(
                json_data={
                    "metadata": {"type": "CityJSON", "version": "2.0", "transform": A,
                                 "metadata": {}},
                    "features": [_city_feature("F1", [[1000, 1000, 0]])],
                    "numberReturned": 1,
                    "links": [{"rel": "next", "href": "http://api/items?offset=1"}],
                }
            )
        return FakeResponse(
            json_data={
                "metadata": {"type": "CityJSON", "version": "2.0", "transform": B,
                             "metadata": {}},
                "features": [_city_feature("F2", [[500, 500, 0]])],
                "numberReturned": 1,
                "links": [],
            }
        )

    aoi = AreaOfInterest(
        name="t", geometry=bbox_polygon((0, 0, 10, 10)), bbox=(0, 0, 10, 10)
    )
    man = DownloadManifest(tmp_path / "manifest.json")
    res = ingest_bag3d(aoi, Bag3DConfig(api_url="http://api"), FakeSession(handler),
                       man, tmp_path / "bag3d")

    assert res["buildings"] == 2
    lines = (tmp_path / "bag3d" / "t.city.jsonl").read_text().splitlines()
    header = json.loads(lines[0])
    assert header["type"] == "CityJSON"
    assert header["transform"] == A

    f1, f2 = json.loads(lines[1]), json.loads(lines[2])
    assert f1["vertices"] == [[1000, 1000, 0]]            # already in transform A
    # F2 re-quantised onto A, but the real-world coordinate is unchanged.
    assert _real(f2["vertices"][0], A) == _real([500, 500, 0], B)
    assert f2["vertices"] == [[1500, 2500, 0]]

    ids = (tmp_path / "bag3d" / "t_buildings.txt").read_text().split()
    assert ids == ["F1", "F2"]
    assert man.is_cached("bag3d:t")


def test_ingest_bag3d_dedupes_repeated_ids(tmp_path):
    def handler(url, params):
        return FakeResponse(
            json_data={
                "metadata": {"type": "CityJSON", "version": "2.0", "transform": A, "metadata": {}},
                "features": [_city_feature("F1", [[0, 0, 0]])],
                "numberReturned": 1,
                "links": [],
            }
        )

    aoi = AreaOfInterest(name="d", geometry=bbox_polygon((0, 0, 1, 1)), bbox=(0, 0, 1, 1))
    man = DownloadManifest(tmp_path / "m.json")
    res = ingest_bag3d(aoi, Bag3DConfig(api_url="http://api"), FakeSession(handler),
                       man, tmp_path / "bag3d")
    assert res["buildings"] == 1
