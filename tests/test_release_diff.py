"""Tests for the read-only published Wiki release comparison."""
from __future__ import annotations

import json

import pytest

from mht.audit import release_diff


def _write_release(root, version, games, pages, schema="1.2.0"):
    outputs = root / version / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "exotica_lit_wiki.json").write_text(
        json.dumps({"header": {"schema_version": schema}, "games": games}),
        encoding="utf-8",
    )
    (outputs / "exotica_wiki_pages_and_redirects.json").write_text(
        json.dumps({"pages": pages}), encoding="utf-8",
    )


def test_counts_content_sections_and_renames(tmp_path, monkeypatch):
    _write_release(tmp_path, "0288", {
        "same": {"wiki_page_name": "Same", "manufacturer": "Foo"},
        "rename": {"wiki_page_name": "Old", "opening_sentence": "Old is a game"},
        "ports": {"wiki_page_name": "Ports", "ports_display": {"Consoles": ["A"]}},
        "gone": {"wiki_page_name": "Gone"},
    }, {"same": "Lost In Translation/Same", "rename": "Lost In Translation/Old", "ports": "Lost In Translation/Ports", "gone": "Lost In Translation/Gone"})
    _write_release(tmp_path, "0289", {
        "same": {"wiki_page_name": "Same", "manufacturer": "Foo"},
        "rename": {"wiki_page_name": "New", "opening_sentence": "New is a game"},
        "ports": {"wiki_page_name": "Ports", "ports_display": {"Consoles": ["B"]}},
        "added": {"wiki_page_name": "Added"},
    }, {"same": "Lost In Translation/Same", "rename": "Lost In Translation/New", "ports": "Lost In Translation/Ports", "added": "Lost In Translation/Added"})
    monkeypatch.setattr(release_diff, "exotica_wiki_path", lambda v: tmp_path / v / "outputs" / "exotica_lit_wiki.json")
    monkeypatch.setattr(release_diff, "exotica_pages_path", lambda v: tmp_path / v / "outputs" / "exotica_wiki_pages_and_redirects.json")

    report = release_diff.compare_wiki_releases("0288", "0289")
    assert report["counts"] == {
        "before_games": 4, "after_games": 4, "added": 1, "withdrawn": 1,
        "modified": 2, "unchanged": 1, "affected_machines": 4,
        "distinct_affected_page_titles": 5, "page_name_changes": 1,
    }
    assert report["modified"]["ports"]["affected_regions"] == ["PORTS"]
    assert report["modified"]["rename"]["page_name_changed"] is True
    assert report["changed_field_counts"]["opening_sentence"] == 1


def test_schema_mismatch_is_rejected(tmp_path, monkeypatch):
    for version, schema in (("0288", "1.1.0"), ("0289", "1.2.0")):
        _write_release(tmp_path, version, {"x": {"wiki_page_name": "X"}}, {"x": "Lost In Translation/X"}, schema)
    monkeypatch.setattr(release_diff, "exotica_wiki_path", lambda v: tmp_path / v / "outputs" / "exotica_lit_wiki.json")
    monkeypatch.setattr(release_diff, "exotica_pages_path", lambda v: tmp_path / v / "outputs" / "exotica_wiki_pages_and_redirects.json")
    with pytest.raises(ValueError, match="schemas differ"):
        release_diff.compare_wiki_releases("0288", "0289")
