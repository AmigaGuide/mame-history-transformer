from pathlib import Path
import json
import pytest

def test_stamp_uses_per_release_encodings(monkeypatch, tmp_path):
    data = tmp_path / "data"
    (data / "releases" / "0281" / "archives").mkdir(parents=True)
    (data / "releases" / "0281" / ".stamps").mkdir(parents=True)
    enc = data / "releases" / "0281" / "encodings.json"
    enc.write_text('{"mame.xml":"utf-8"}', encoding="utf-8")
    # fake mame zip presence
    (data / "releases" / "0281" / "archives" / "mame0281lx.zip").write_bytes(b"PK\x03\x04DUMMY")

    import mht.utils.paths as upaths
    monkeypatch.setattr(upaths, "DATA_DIR", data, raising=False)
    # active_version -> 0281
    #monkeypatch.setattr(upaths, "active_version", lambda: "0281", raising=False)
    monkeypatch.setattr(upaths, "active_version", lambda *a, **k: "0281", raising=False)

    # Call the codepath that generates the stamp for MAME
    from mht.inputs.mame_parser import stage_is_fresh
    fresh, stamp_path, cur = stage_is_fresh(
        "mame.json",
        schema_id="mht.stage.mame",
        tool="mame_parser",
        inputs=[(data / "releases" / "0281" / "archives" / "mame0281lx.zip"), enc],
    )
    # Now write the stamp and re-evaluate freshness; the specifics of stage_is_fresh may differ,
    # adjust if your helper already writes. Here we just assert the inputs are correct:
    assert any(str(i["path"]).endswith("/releases/0281/encodings.json") for i in cur.get("inputs", [])), \
        "stamp must reference per-release encodings.json"
