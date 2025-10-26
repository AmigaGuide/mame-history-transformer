from pathlib import Path
import json
import pytest

def test_releases_index_builds_with_posix_paths(monkeypatch, tmp_path):
    data = tmp_path / "data"
    (data / "releases" / "0280" / "archives").mkdir(parents=True)
    (data / "releases" / "0280" / "outputs").mkdir(parents=True)
    (data / "releases" / "0280" / "summaries").mkdir(parents=True)
    (data / "releases" / "0280").joinpath("encodings.json").write_text("{}", encoding="utf-8")

    # Create a couple of dummy outputs/summaries
    (data / "releases" / "0280" / "outputs" / "mame_machines.json").write_text("{}", encoding="utf-8")
    (data / "releases" / "0280" / "summaries" / "mame_parsing_summary.json").write_text("{}", encoding="utf-8")

    import mht.utils.paths as upaths
    monkeypatch.setattr(upaths, "DATA_DIR", data, raising=False)

    from mht.provenance.releases_index import rebuild_releases_index
    entries = rebuild_releases_index()
    assert isinstance(entries, list) and entries, "index should list at least one release"
    e0 = entries[0]
    # POSIX style paths
    assert e0["paths"]["root"].startswith("data/"), "should use as_posix()"
    # Encodings present
    assert "encodings" in e0 and e0["encodings"]["path"].endswith("/encodings.json")
    # Outputs & summaries included
    assert any(x["path"].endswith("/outputs/mame_machines.json") for x in e0.get("outputs", []))
    assert any(x["path"].endswith("/summaries/mame_parsing_summary.json") for x in e0.get("summaries", []))

    # Also check file is written next to data dir root if that’s your implementation
    idx = data / "releases_index.json"
    assert idx.exists(), "should write releases_index.json"
    doc = json.loads(idx.read_text(encoding="utf-8"))
    assert isinstance(doc, list)
