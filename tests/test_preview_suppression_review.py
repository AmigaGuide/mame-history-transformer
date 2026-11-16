"""Focused Preview tests for existing GH suppression evidence."""
from mht.preview.app import create_app
from mht.preview.diagnostics import build_diagnostic_groups
from mht.preview.history_suppression_review import (
    MAX_LINES, build_machine_suppression_review,
)
from mht.preview.preview_data import PreviewData


def sample():
    return {
        "suppressions": {
            "counts": {"total": 2, "technical_cpu_line": 1, "overview_type_line": 1},
            "by_system": {
                "pacman": [
                    {"section": "overview", "rule": "overview_type_line", "line": "<arcade>"},
                    {"section": "technical", "rule": "technical_cpu_line", "line": "CPU: Z80"},
                ],
            },
        },
        "fully_suppressed_sections": {"technical": ["pacman"], "overview": ["other"]},
    }


def data(summary):
    return PreviewData(
        wiki_doc={}, wiki_games={},
        trivia_by_machine={"pacman": {"sections": {}}, "other": {"sections": {}}},
        mame_machines={"pacman": {"description": "Pac-Man"}},
        mame_summary={}, history_summary=summary, ini_summary={},
        transform_summary={}, machine_order=["pacman", "other"],
    )


def test_retains_recorded_lines_and_section_names_without_inventing_errors():
    r = build_machine_suppression_review(sample(), "pacman")
    assert r["has_evidence"] is True and r["line_count"] == 2
    assert r["lines"][0]["line"] == "<arcade>"
    assert r["fully_suppressed"] == ["technical"]
    assert build_machine_suppression_review({}, "pacman")["has_evidence"] is False


def test_fully_suppressed_section_without_recorded_line_is_still_visible():
    r = build_machine_suppression_review(sample(), "other")
    assert r["has_evidence"] and r["line_count"] == 0
    assert r["fully_suppressed"] == ["overview"]


def test_display_cap_and_summary_immutability():
    s = sample()
    s["suppressions"]["by_system"]["pacman"] *= MAX_LINES
    r = build_machine_suppression_review(s, "pacman")
    assert len(r["lines"]) == MAX_LINES
    assert r["lines_omitted"] == MAX_LINES
    assert len(s["suppressions"]["by_system"]["pacman"]) == MAX_LINES * 2


def test_game_page_escapes_source_and_keeps_separate_suppression_review():
    app = create_app(data(sample()), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/game/pacman").get_data(as_text=True)
    assert 'id="suppression-review"' in html
    assert 'href="#suppression-review"' in html
    assert "&lt;arcade&gt;" in html and "<arcade>" not in html
    assert "Sections completely removed" in html
    assert "not automatically errors" in html
    html2 = app.test_client().get("/game/other").get_data(as_text=True)
    assert "overview" in html2 and 'id="suppression-review"' in html2


def test_diagnostics_counts_are_source_backed_and_link_machine():
    groups = build_diagnostic_groups(data(sample()))
    findings = groups[1]["findings"]
    s = next(x for x in findings if x["label"] == "Suppressed GH Trivia source lines")
    f = next(x for x in findings if x["label"] == "GH Trivia sections with no surviving content")
    assert s["count"] == 2 and s["game_anchor"] == "suppression-review"
    assert f["count"] == 2 and f["game_anchor"] == "suppression-review"
    app = create_app(data(sample()), version="0289")
    html = app.test_client().get("/diagnostics").get_data(as_text=True)
    assert '/game/pacman#suppression-review' in html
    assert '/game/other#suppression-review' in html


def test_missing_or_malformed_suppression_counts_not_invented():
    groups = build_diagnostic_groups(data({"suppressions": {"counts": {"total": "unknown"}}}))
    assert not any(x["label"] == "Suppressed GH Trivia source lines" for x in groups[1]["findings"])
    r = build_machine_suppression_review({"suppressions": {"by_system": {"pacman": "bad"}}}, "pacman")
    assert not r["has_evidence"]
