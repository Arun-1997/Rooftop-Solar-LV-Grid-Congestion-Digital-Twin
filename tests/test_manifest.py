from rsgt.ingest.manifest import DownloadManifest, sha256_file


def test_record_and_cache(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    f = raw / "thing.bin"
    f.write_bytes(b"hello world")

    man = DownloadManifest(raw / "manifest.json")
    assert not man.is_cached("k1")
    entry = man.record(key="k1", source="test", url="http://x", path=f)
    assert entry.bytes == 11
    assert entry.path == "thing.bin"  # stored relative to manifest root
    assert man.is_cached("k1")
    assert man.is_cached("k1", verify=True)


def test_cache_invalid_when_size_changes(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    f = raw / "thing.bin"
    f.write_bytes(b"hello")
    man = DownloadManifest(raw / "manifest.json")
    man.record(key="k", source="t", url="u", path=f)
    f.write_bytes(b"hello world longer")  # changed on disk
    assert not man.is_cached("k")  # size mismatch -> not cached


def test_persist_roundtrip(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    f = raw / "a.bin"
    f.write_bytes(b"data")
    man = DownloadManifest(raw / "manifest.json")
    man.record(key="a", source="t", url="u", path=f)
    man.save()

    reloaded = DownloadManifest(raw / "manifest.json")
    assert reloaded.is_cached("a")
    assert reloaded.get("a").sha256 == sha256_file(f)
