"""Regression tests for merging Wiki changes with rendered GH Trivia sections."""
from __future__ import annotations

import json

from mht.audit import combined_diff, release_diff, trivia_diff


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_combined_diff_counts_each_machine_once(tmp_path, monkeypatch):
    for version, games, trivia in (
        ("0288", {
            "same": {"wiki_page_name": "Same"},
            "wiki_change": {"wiki_page_name": "Old"},
            "both": {"wiki_page_name": "Both", "manufacturer": "A"},
            "trivia_only": {"wiki_page_name": "Trivia"},
            "withdrawn": {"wiki_page_name": "Withdrawn"},
        }, {
            "both": {"sections": {"trivia": {"blocks": [{"type": "paragraph", "text": "Old", "meta": {"block_index": 0}}]}}},
            "trivia_only": {"sections": {"technical": {"blocks": [{"type": "paragraph", "text": "A"}]}}},
        }),
        ("0289", {
            "same": {"wiki_page_name": "Same"},
            "wiki_change": {"wiki_page_name": "New"},
            "both": {"wiki_page_name": "Both", "manufacturer": "B"},
            "trivia_only": {"wiki_page_name": "Trivia"},
            "added": {"wiki_page_name": "Added"},
        }, {
            "both": {"sections": {"trivia": {"blocks": [{"type": "paragraph", "text": "New", "meta": {"block_index": 9}}]}}},
            "trivia_only": {"sections": {"technical": {"blocks": [{"type": "paragraph", "text": "B"}]}}},
        }),
    ):
        output = tmp_path / version / "outputs"
        _write(output / "exotica_lit_wiki.json", {"header": {"schema_version": "1.2.0"}, "games": games})
        pages = {k: f"Lost In Translation/{v['wiki_page_name']}" for k, v in games.items()}
        _write(output / "exotica_wiki_pages_and_redirects.json", {"pages": pages})
        _write(output / "gh_system_trivia.json", trivia)

    monkeypatch.setattr(release_diff, "exotica_wiki_path", lambda v: tmp_path / v / "outputs/exotica_lit_wiki.json")
    monkeypatch.setattr(release_diff, "exotica_pages_path", lambda v: tmp_path / v / "outputs/exotica_wiki_pages_and_redirects.json")
    monkeypatch.setattr(trivia_diff, "gh_system_trivia_path", lambda v: tmp_path / v / "outputs/gh_system_trivia.json")

    result = combined_diff.compare_release_content("0288", "0289")
    counts = result["counts"]
    assert counts["wiki_affected_machines"] == 4  # rename, both, add, withdraw
    assert counts["trivia_changed_machines"] == 2
    assert counts["changed_in_both"] == 1
    assert counts["trivia_only_machines"] == 1
    assert counts["affected_machines"] == 5
    assert counts["distinct_affected_page_titles"] == 6  # old and new rename
    assert counts["changed_trivia_sections"] == 2
    assert result["affected"]["trivia_only"]["trivia_sections"] == ["technical"]
    assert result["affected"]["both"]["wiki_regions"] == ["MAME information panel"]
    assert result["affected"]["withdrawn"]["status"] == "withdrawn"
    assert "GH Trivia: technical" in result["affected_region_counts"]
