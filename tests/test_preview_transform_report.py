"""Phase 10E - source-backed compact Transformation summary regression tests."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData
from mht.preview.transform_report import build_transform_report


def _data(summary):
    return PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                       mame_summary={}, history_summary={}, ini_summary={},
                       transform_summary=summary, machine_order=[])


def test_raw_included_is_distinct_from_publication():
    report = build_transform_report({"counts": {"final_included": 50},
                                     "publication": {"raw_parents": 50, "published_parents": 32,
                                                     "deferred_parents": 18}})
    assert [(x["path"], x["value"]) for x in report["stages"]] == [
        ("publication.raw_parents", 50), ("publication.published_parents", 32),
        ("publication.deferred_parents", 18)]


def test_legacy_fallback_does_not_invent_published_count():
    report = build_transform_report({"counts": {"final_included": 20}})
    assert report["stages"] == [{"label": "PORTS-bearing parents retained in raw data (legacy)",
                                  "value": 20, "path": "counts.final_included"}]


def test_missing_is_distinct_from_zero():
    report = build_transform_report({"publication": {"published_parents": 0}})
    assert len(report["stages"]) == 1
    assert report["stages"][0]["value"] == 0
    assert build_transform_report({})["stages"] == []


def test_five_examples_limit_without_dict_repr():
    summary = {"counts": {"audio": {"channel_speaker_mismatches": 9,
                "mismatch_examples": [{"machine": f"m{i}", "sound_channels": 2} for i in range(9)]}}}
    finding = build_transform_report(summary)["findings"][0]
    assert finding["count"] == 9
    assert finding["examples"] == ["m0", "m1", "m2", "m3", "m4"]


def test_zero_findings_omitted():
    assert build_transform_report({"counts": {"audio": {"channel_speaker_mismatches": 0}},
        "wiki_navigation": {"conflicts_total": 0}})["findings"] == []


def test_publication_reasons_ranked_and_bounded():
    report = build_transform_report({"publication": {
        "deferred_by_reason": {f"reason{i}": i for i in range(15)}}})
    group = report["publication_reasons"]
    assert group["total"] == 15 and len(group["rows"]) == 12
    assert group["rows"][0]["count"] == 14


def test_snaps_is_recorded_coverage_not_eligibility_inference():
    report = build_transform_report({"snaps_coverage": {"classifications_total": 800,
        "ports_parents_classified": 40, "ports_parents_missing": 10}})
    assert [m["value"] for m in report["snaps"]] == [800, 40, 10]
    assert report["stages"] == []


def test_artifacts_do_not_show_hashes_or_nested_data():
    report = build_transform_report({"provenance": {"inputs": [
        {"path": "data/input.json", "missing": True, "sha256": "PRIVATE_TEST_HASH"},
        {"path": "data/snaps.zip", "kind": "snaps_catlist_archive", "classifications": 400}],
        "outputs": [{"path": "data/raw.json", "records": 20}]}})
    assert report["inputs"][0]["missing"] is True
    assert report["inputs"][1]["kind"] == "snaps_catlist_archive"
    assert report["outputs"][0]["records"] == 20
    assert "PRIVATE_TEST_HASH" not in str(report)


def test_summary_html_does_not_expand_dictionary_or_sample_data():
    summary = {"header": {"versions": {"transformer_version": "1.2"}},
        "publication": {"raw_parents": 9, "published_parents": 4,
                        "deferred_by_reason": {"not_arcade": 5}},
        "counts": {"audio": {"channel_speaker_mismatches": 7,
                           "mismatch_examples": [{"machine": f"machine{i}", "debug": "SECRET_VALUE"}
                                                 for i in range(7)]}}}
    app = create_app(_data(summary), version="0289")
    app.config.update(TESTING=True)
    response = app.test_client().get("/summary/transform")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "published to ExoticA" in html
    assert "data/releases/0289/summaries/transform_summary.json" in html
    assert "machine4" in html and "machine5" not in html
    assert "SECRET_VALUE" not in html
    assert "'mismatch_examples':" not in html
    assert "/diagnostics" in html


def test_empty_summary_renders_without_guessing_values():
    app = create_app(_data({}), version="0289")
    app.config.update(TESTING=True)
    result = app.test_client().get("/summary/transform")
    assert result.status_code == 200
    assert b"No selection or publication totals recorded" in result.data
