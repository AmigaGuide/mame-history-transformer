"""Coverage tests for source-backed GH summary observations in Preview."""
from mht.preview.app import create_app
from mht.preview.diagnostics import build_diagnostic_groups
from mht.preview.history_structural_observations import build_machine_structural_observations
from mht.preview.preview_data import PreviewData


def summary():
    return {
        "anomalies": {
            "unexpected_platform_categories": {
                "unique": 2, "systems_affected": 2,
                "by_category": {
                    "<DIGITAL>": {"systems_count": 1, "systems": ["pacman"]},
                    "OTHER": {"systems_count": 2, "systems": ["pacman", "other"]},
                },
            },
            "platform_banners": {"count": 3, "systems_affected": 1,
                                 "by_system": {"pacman": {"count": 3, "banners": {"-HELLO-": 2, "<x>": 1}}}},
        },
        "residue_flags": {"systems_with_residue": {"count": 1, "items": ["pacman"]}},
    }


def data(value=None):
    return PreviewData(
        wiki_doc={}, wiki_games={}, trivia_by_machine={"pacman": {"sections": {}}, "other": {"sections": {}}},
        mame_machines={"pacman": {"description": "Pac-Man"}},
        mame_summary={}, history_summary=summary() if value is None else value,
        ini_summary={}, transform_summary={}, machine_order=["pacman", "other"],
    )


def test_machine_observations_retain_category_names_and_banner_counts():
    rows = build_machine_structural_observations(summary(), "pacman")
    by_label = {row["label"]: row for row in rows}
    assert by_label["Unexpected PORTS category names"]["items"] == ["<DIGITAL>", "OTHER"]
    assert "not verbatim" in by_label["Unexpected PORTS category names"]["source_label"]
    assert by_label["PORTS platform banners"]["items"] == ["-HELLO- (2 occurrence(s))", "<x> (1 occurrence(s))"]
    assert by_label["Recorded residue flag"]["items"] == []
    assert "does not specify the cause" in by_label["Recorded residue flag"]["description"]


def test_machine_membership_only_and_no_inferred_findings():
    assert [row["label"] for row in build_machine_structural_observations(summary(), "other")] == ["Unexpected PORTS category names"]
    assert build_machine_structural_observations({}, "pacman") == []
    assert build_machine_structural_observations(summary(), "unknown") == []


def test_diagnostics_use_real_counts_and_machine_examples():
    findings = {f["label"]: f for f in build_diagnostic_groups(data())[1]["findings"]}
    assert findings["Unexpected PORTS category names"]["count"] == 2
    assert findings["Unexpected PORTS category names"]["systems_affected"] == 2
    assert findings["Unexpected PORTS category names"]["count_label"] == "Distinct categories"
    assert findings["PORTS platform banners"]["count"] == 3
    assert findings["PORTS platform banners"]["systems_affected"] == 1
    assert findings["Systems with recorded residue"]["count"] == 1
    assert findings["Systems with recorded residue"]["example_items"][0]["machine"] == "pacman"


def test_game_escapes_labels_and_links_to_observations():
    app = create_app(data(), version="0289")
    app.config.update(TESTING=True)
    page = app.test_client().get("/game/pacman").get_data(as_text=True)
    assert "&lt;DIGITAL&gt;" in page and "<DIGITAL>" not in page
    assert "&lt;x&gt; (1 occurrence(s))" in page
    assert "Recorded residue flag" in page
    listing = app.test_client().get("/diagnostics").get_data(as_text=True)
    assert '/game/pacman#structural-observations' in listing
    assert 'Unexpected PORTS category names' in listing


def test_malformed_metrics_do_not_create_fabricated_diagnostics():
    malformed = {"anomalies": {"unexpected_platform_categories": {"unique": "two"},
                               "platform_banners": {"count": True}},
                 "residue_flags": {"systems_with_residue": {"count": None}}}
    findings = [f["label"] for f in build_diagnostic_groups(data(malformed))[1]["findings"]]
    assert "Unexpected PORTS category names" not in findings
    assert "PORTS platform banners" not in findings
    assert "Systems with recorded residue" not in findings


def test_missing_game_does_not_infer_wiki_publication():
    app = create_app(data(), version="0289")
    app.config.update(TESTING=True)
    html = app.test_client().get("/game/pacman").get_data(as_text=True)
    assert "GH Trivia preview only" in html
