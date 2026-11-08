"""Phase 9A regression tests for summary-backed source provenance."""
from __future__ import annotations

from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData
from mht.preview.provenance import build_source_provenance


def make_data(**overrides):
    fields = dict(
        wiki_doc={"games": {}}, wiki_games={}, trivia_by_machine={}, mame_machines={},
        mame_summary={}, history_summary={}, ini_summary={}, transform_summary={},
        machine_order=[],
    )
    fields.update(overrides)
    return PreviewData(**fields)


def test_mame_member_and_archive_are_independent():
    s = {"header": {"versions": {"mame_xml_version": "0.289"}},
         "provenance": {"inputs": [{"zip_archive": "mame0289.zip", "zip_member": "mame.xml"}]}}
    fields = build_source_provenance(make_data(mame_summary=s))["mame"]
    assert fields["filename"] == "mame.xml"
    assert fields["archive"] == "mame0289.zip"
    assert fields["xml_version"] == "0.289"


def test_missing_mame_provenance_does_not_invent_filename():
    assert build_source_provenance(make_data())["mame"]["filename"] is None


def test_placeholder_history_name_not_presented_as_evidence():
    s = {"provenance": {"inputs": [{"name": "history.xml"}]}}
    assert build_source_provenance(make_data(history_summary=s))["history"]["filename"] is None


def test_history_declared_version_remains_from_header():
    s = {"header": {"versions": {"gh_version": "1.2", "gh_date": "2026-05-01"}},
         "provenance": {"inputs": [{"zip_member": "history/history.xml", "zip_archive": "gh.zip",
                                    "zip_member_modified": "2026-05-02T11:00:00"}]}}
    history = build_source_provenance(make_data(history_summary=s))["history"]
    assert history["date"] == "2026-05-01"
    assert history["modified"] == "2026-05-02T11:00:00"


def test_ini_three_members_are_displayed_in_canonical_order():
    items = [{"zip_member": "Game Or No Game.ini", "zip_archive": "bundle.zip"},
             {"zip_member": "Machine Category.ini"},
             {"zip_member": "Machine Type.ini"}]
    ini = build_source_provenance(make_data(ini_summary={"provenance": {"inputs": items}}))["ini"]
    assert [f["filename"] for f in ini["files"]] == [
        "Game Or No Game.ini", "Machine Category.ini", "Machine Type.ini"]
    assert ini["files"][0]["archive"] == "bundle.zip"


def test_ini_fallback_keys_are_not_treated_as_filenames():
    ini = {"provenance": {"inputs": [
        {"name": "game_status"}, {"name": "category"}, {"name": "type"}]},
        "ini": {"files": {"game_status": {"filename": "game_status"},
                           "category": {"filename": "category"},
                           "type": {"filename": "type"}}}}
    files = build_source_provenance(make_data(ini_summary=ini))["ini"]["files"]
    assert all(f["filename"] is None for f in files)


def test_ini_filenames_can_fall_back_to_explicit_file_stats():
    ini = {"ini": {"files": {"category": {"filename": "custom_category.ini"}}}}
    files = build_source_provenance(make_data(ini_summary=ini))["ini"]["files"]
    assert files[1]["filename"] == "custom_category.ini"


def test_landing_page_renders_source_provenance():
    data = make_data(mame_summary={"provenance": {"inputs": [{
        "zip_archive": "mame0289.zip", "zip_member": "mame.xml"}]}})
    app = create_app(data, version="0289")
    app.config.update(TESTING=True)
    page = app.test_client().get("/")
    assert page.status_code == 200
    assert b"mame0289.zip" in page.data
    assert b"not recorded in summary" in page.data
    assert b"Game Or No Game.ini" in page.data
