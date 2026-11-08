"""Phase 10C: bounded, canonical MAME parsing report."""
from __future__ import annotations

from mht.preview.mame_report import build_mame_report
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData


def _app(summary):
    data = PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                       mame_summary=summary, history_summary={}, ini_summary={},
                       transform_summary={}, machine_order=[])
    app = create_app(data, version="0289")
    app.config["TESTING"] = True
    return app


def test_canonical_totals_and_no_alias_double_count():
    r = build_mame_report({"totals": {"total_machines": 7, "total_isbios": 2, "total_is_bios": 2}})
    assert [(m["label"], m["value"]) for m in r["metrics"]] == [
        ("Machines parsed", 7), ("BIOS machines", 2)]


def test_real_schema_nested_distributions_ranked_and_bounded():
    data = {str(i): i for i in range(30)}
    r = build_mame_report({"totals": {"players": {"distribution": data, "sum": 435}}})
    d = r["distributions"][0]
    assert d["label"] == "Players per machine" and d["total_groups"] == 30
    assert len(d["rows"]) == 12 and d["rows"][0] == {"name": "29", "count": 29}


def test_controls_use_nested_distribution():
    r = build_mame_report({"totals": {"controls": {"types_overall": {"distribution": {"joystick": 12}}}}})
    assert r["distributions"][0]["path"] == "totals.controls.types_overall.distribution"


def test_dropped_displays_mirror_only_once_and_examples_bounded():
    drop = {"count": 9, "examples": [
        {"machine": f"game{i}", "type": "raster", "width": 384, "height": 0} for i in range(8)]}
    r = build_mame_report({"totals": {"invalid_displays_dropped": drop},
                           "anomalies": {"dropped_displays": drop}})
    assert len(r["findings"]) == 1
    assert r["findings"][0]["count"] == 9
    assert len(r["findings"][0]["examples"]) == 5
    assert r["findings"][0]["examples"][0]["machine"] == "game0"


def test_fallback_to_anomaly_mirror_when_legacy_missing():
    r = build_mame_report({"anomalies": {"dropped_displays": {"count": 3}}})
    assert r["findings"][0]["path"] == "anomalies.dropped_displays"


def test_missing_counts_do_not_become_zero_or_raw_objects():
    r = build_mame_report({"totals": {"players": {"distribution": {"x": {"count": 8}}},
                                      "invalid_displays_dropped": {"count": None}}})
    assert r["metrics"] == [] and r["findings"] == [] and r["distributions"] == []


def test_mame_page_excludes_nested_json_and_shows_evidence():
    s = {"header": {"versions": {"mame_build": "0.289 (mame0289)"}},
         "totals": {"players": {"distribution": {"one": 7, "two": 3}, "sentinel": "DONT_PRINT"}}}
    result = _app(s).test_client().get("/summary/mame")
    assert result.status_code == 200
    html = result.get_data(as_text=True)
    assert "0.289 (mame0289)" in html
    assert "mame_parsing_summary.json" in html
    assert "totals.players.distribution" in html
    assert "DONT_PRINT" not in html and "{'distribution':" not in html
    assert "/diagnostics" in html


def test_missing_mame_summary_still_renders():
    result = _app({}).test_client().get("/summary/mame")
    assert result.status_code == 200
    assert b"No recognised totals recorded" in result.data


def test_zero_dropped_displays_are_not_a_finding():
    assert build_mame_report({"totals": {"invalid_displays_dropped": {"count": 0}}})["findings"] == []
