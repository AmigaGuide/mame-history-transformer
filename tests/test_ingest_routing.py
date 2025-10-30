def _touch_zip(dir, name):
    p = dir / name
    p.write_bytes(b"PK\x03\x04DUMMY")  # minimal local file header; we won't unzip
    return p

def test_ingest_prefers_forced_version_then_filename(monkeypatch, tmp_path):
    # Arrange faux data layout
    data = tmp_path / "data"
    (data / "incoming").mkdir(parents=True)
    (data / "quarantine").mkdir(parents=True)

    # Put two zips in incoming
    _touch_zip(data / "incoming", "history281.zip")
    _touch_zip(data / "incoming", "mame0281lx.zip")

    # Monkeypatch DATA_DIR and active_version()
    import mht.utils.paths as upaths
    monkeypatch.setattr(upaths, "DATA_DIR", data, raising=False)
    monkeypatch.setattr(upaths, "active_version", lambda *a, **k: "0280", raising=False)

    # Ensure release helpers work under patched DATA_DIR
    from mht.provenance.archives import import_incoming_archives
    res = import_incoming_archives(incoming=data / "incoming", extract=False, version=None)

    # Defensive: exactly two results expected
    assert len(res) == 2

    # Both should have landed under 0281 by filename hint
    assert any(r.get("dest_archive", "").endswith("/releases/0281/archives/mame0281lx.zip") for r in res)
    assert any(r.get("dest_archive", "").endswith("/releases/0281/archives/history281.zip") for r in res)

    # If we force 0282, both should go to 0282 regardless of names
    _touch_zip(data / "incoming", "history281.zip")
    _touch_zip(data / "incoming", "mame0281lx.zip")

    res_forced = import_incoming_archives(incoming=data / "incoming", extract=False, version="0282")
    assert len(res_forced) == 2
    assert all("/releases/0282/archives/" in (r.get("dest_archive") or "") for r in res_forced)
