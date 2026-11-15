"""Selected-stage GH encoding refresh: reusable detector, failure safety, cache isolation."""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from mht.utils import gh_encoding_refresh as refresh
from mht.utils.gh_encoding_guard import check_gh_encoding_cache


def _sources(tmp_path):
    mame = tmp_path / "mame0289lx.zip"
    original = tmp_path / "history289.zip"
    revised = tmp_path / "history289a.zip"
    with ZipFile(mame, "w") as zf:
        zf.writestr("mame.xml", b'<?xml version="1.0" encoding="utf-8"?><mame build="0.289"/>')
    for archive, label in [(original, b"old"), (revised, b"new")]:
        with ZipFile(archive, "w") as zf:
            zf.writestr("history.xml", b'<?xml version="1.0" encoding="utf-8"?><history version="2.89">' + label + b'</history>')
            zf.writestr("[GAMING HISTORY] Game Or No Game.ini", b"[Game]\n" + label)
            zf.writestr("[GAMING HISTORY] Machine Type.ini", b"[Type]\n" + label)
    def records(archive):
        with ZipFile(archive) as zf:
            return {Path(i.filename).name: {
                "encoding":"utf-8", "zip_archive": archive.name,
                "zip_member":i.filename, "zip_crc32":i.CRC,
                "zip_size_bytes":i.file_size,
            } for i in zf.infolist()}
    cache = tmp_path / "encodings.json"
    initial = {**records(original), **records(mame)}
    cache.write_text(json.dumps(initial),encoding="utf-8")
    return mame, revised, cache, initial


def test_real_detector_refreshes_gh_and_preserves_mame(tmp_path):
    mame, gh, cache, prior = _sources(tmp_path)
    assert refresh.ensure_gh_encodings("0289", gh, "ini", cache_path=cache, mame_archive=mame)
    updated = json.loads(cache.read_text(encoding="utf-8"))
    assert updated["mame.xml"] == prior["mame.xml"]
    assert updated["history.xml"]["zip_archive"] == "history289a.zip"
    assert updated["[GAMING HISTORY] Machine Type.ini"]["zip_archive"] == "history289a.zip"
    assert "[GAMING HISTORY] Machine Category.ini" not in updated
    check_gh_encoding_cache("0289", gh, "history", cache_path=cache)
    check_gh_encoding_cache("0289", gh, "ini", cache_path=cache)


def test_second_call_is_noop_and_does_not_rewrite_cache(tmp_path, monkeypatch):
    mame, gh, cache, _ = _sources(tmp_path)
    refresh.ensure_gh_encodings("0289", gh, "history", cache_path=cache, mame_archive=mame)
    before = cache.read_bytes()
    monkeypatch.setattr(refresh, "detect_encodings_from_archives", lambda **kw: pytest.fail("should not detect"))
    assert not refresh.ensure_gh_encodings("0289", gh, "history", cache_path=cache, mame_archive=mame)
    assert cache.read_bytes() == before


def test_detector_failure_preserves_cache(tmp_path, monkeypatch):
    mame, gh, cache, _ = _sources(tmp_path)
    before = cache.read_bytes()
    def fail(**kwargs):
        raise OSError("simulated read failure")
    monkeypatch.setattr(refresh, "detect_encodings_from_archives", fail)
    with pytest.raises(ValueError, match="GH encoding detection failed"):
        refresh.ensure_gh_encodings("0289", gh, "history", cache_path=cache, mame_archive=mame)
    assert cache.read_bytes() == before


def test_detector_mame_change_rejected(tmp_path, monkeypatch):
    mame, gh, cache, prior = _sources(tmp_path)
    before = cache.read_bytes()
    def bad(**kwargs):
        data = dict(prior)
        data["mame.xml"] = dict(data["mame.xml"], encoding="windows-1252")
        return data, True
    monkeypatch.setattr(refresh, "detect_encodings_from_archives", bad)
    with pytest.raises(ValueError, match="MAME encoding provenance would change"):
        refresh.ensure_gh_encodings("0289", gh, "ini", cache_path=cache, mame_archive=mame)
    assert cache.read_bytes() == before


def test_incomplete_detector_result_rejected(tmp_path, monkeypatch):
    mame, gh, cache, prior = _sources(tmp_path)
    before = cache.read_bytes()
    monkeypatch.setattr(refresh, "detect_encodings_from_archives", lambda **kw: (prior, False))
    with pytest.raises(ValueError, match="Refreshed GH encoding provenance invalid"):
        refresh.ensure_gh_encodings("0289", gh, "ini", cache_path=cache, mame_archive=mame)
    assert cache.read_bytes() == before


def test_malformed_existing_cache_rejected_without_detection(tmp_path, monkeypatch):
    mame, gh, cache, _ = _sources(tmp_path)
    cache.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(refresh, "detect_encodings_from_archives", lambda **kw: pytest.fail("should not detect"))
    with pytest.raises(ValueError, match="Cannot read encoding cache"):
        refresh.ensure_gh_encodings("0289", gh, "history", cache_path=cache, mame_archive=mame)
    assert cache.read_text(encoding="utf-8") == "{broken"


def test_missing_mame_archive_rejected(tmp_path):
    mame, gh, cache, _ = _sources(tmp_path)
    before = cache.read_bytes()
    with pytest.raises(ValueError, match="without a staged MAME ZIP"):
        refresh.ensure_gh_encodings("0289", gh, "history", cache_path=cache, mame_archive=None)
    assert cache.read_bytes() == before


def test_refresh_preserves_other_keys(tmp_path):
    mame, gh, cache, prior = _sources(tmp_path)
    prior["unrelated"] = {"keep": "value"}
    cache.write_text(json.dumps(prior),encoding="utf-8")
    refresh.ensure_gh_encodings("0289", gh, "ini", cache_path=cache, mame_archive=mame)
    assert json.loads(cache.read_text(encoding="utf-8"))["unrelated"] == {"keep":"value"}
