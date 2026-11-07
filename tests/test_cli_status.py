"""Regression coverage for MHT status freshness."""
from __future__ import annotations

import argparse
import json

from mht import cli
from mht.utils.stamps import make_stamp, save_stamp
from mht.utils.versions import tool_version


def _files(tmp_path):
    inp = tmp_path / "source.zip"
    out = tmp_path / "output.json"
    stamps = tmp_path / ".stamps"
    stamps.mkdir()
    inp.write_bytes(b"initial")
    out.write_text("{}", encoding="utf-8")
    return inp, out, stamps


def _save_fresh_stamp(inp, stamps):
    save_stamp(
        stamps / "mame.json",
        make_stamp("mht.stage.mame", tool_version("mame_parser"), [inp]),
    )


def _evaluate(monkeypatch, inp, out, stamps):
    monkeypatch.setattr(cli, "stamps_dir", lambda version: stamps)
    return cli._evaluate_stage(
        name="mame",
        schema_id="mht.stage.mame",
        tool="mame_parser",
        inputs=[inp],
        outputs=[out],
        version="0284",
    )


def test_fresh_when_stamp_inputs_and_outputs_match(tmp_path, monkeypatch):
    inp, out, stamps = _files(tmp_path)
    _save_fresh_stamp(inp, stamps)
    assert _evaluate(monkeypatch, inp, out, stamps)["fresh"] is True


def test_stale_when_required_output_removed(tmp_path, monkeypatch):
    inp, out, stamps = _files(tmp_path)
    _save_fresh_stamp(inp, stamps)
    out.unlink()
    result = _evaluate(monkeypatch, inp, out, stamps)
    assert result["fresh"] is False
    assert str(out) in result["missing_outputs"]


def test_stale_when_source_changes(tmp_path, monkeypatch):
    inp, out, stamps = _files(tmp_path)
    _save_fresh_stamp(inp, stamps)
    inp.write_bytes(b"changed source with different size")
    assert _evaluate(monkeypatch, inp, out, stamps)["fresh"] is False


def test_stale_when_source_is_missing(tmp_path, monkeypatch):
    inp, out, stamps = _files(tmp_path)
    _save_fresh_stamp(inp, stamps)
    inp.unlink()
    result = _evaluate(monkeypatch, inp, out, stamps)
    assert result["fresh"] is False
    assert str(inp) in result["missing_inputs"]


def test_stale_when_stamp_missing(tmp_path, monkeypatch):
    inp, out, stamps = _files(tmp_path)
    result = _evaluate(monkeypatch, inp, out, stamps)
    assert result["fresh"] is False
    assert result["stamp_present"] is False


def test_missing_required_archive_overrides_matching_stamp(tmp_path, monkeypatch):
    inp, out, stamps = _files(tmp_path)
    _save_fresh_stamp(inp, stamps)
    monkeypatch.setattr(cli, "stamps_dir", lambda version: stamps)
    result = cli._evaluate_stage(
        name="mame", schema_id="mht.stage.mame", tool="mame_parser",
        inputs=[inp], outputs=[out], version="0284", missing_source=True,
    )
    assert result["fresh"] is False
    assert result["missing_source"] is True


def test_text_and_json_status_use_same_results(tmp_path, monkeypatch, capsys):
    root = tmp_path / "release"
    archives = root / "archives"
    archives.mkdir(parents=True)
    (archives / "history.zip").write_bytes(b"history")
    (archives / "mame.zip").write_bytes(b"mame")

    locations = {
        "release_root": root,
        "archives_dir": archives,
        "stamps_dir": root / ".stamps",
        "encodings_cache_path": root / "encodings.json",
        "mame_xml_path": root / "extracted/mame.xml",
        "mame_machines_path": root / "outputs/mame_machines.json",
        "parent_index_path": root / "outputs/mame_parent_index.json",
        "mame_summary_path": root / "summaries/mame_parsing_summary.json",
        "ini_classifications_path": root / "outputs/gh_ini_classifications.json",
        "ini_summary_path": root / "summaries/ini_parsing_summary.json",
        "gh_system_ports_path": root / "outputs/gh_system_ports.json",
        "gh_system_trivia_path": root / "outputs/gh_system_trivia.json",
        "history_summary_path": root / "summaries/history_parsing_summary.json",
        "exotica_wiki_path": root / "outputs/exotica_lit_wiki.json",
        "exotica_raw_path": root / "outputs/exotica_lit_raw_data.json",
        "exotica_pages_path": root / "outputs/exotica_wiki_pages_and_redirects.json",
        "transform_summary_path": root / "summaries/transform_summary.json",
    }
    # The central contract resolves release paths via utils.paths.
    from mht.utils import stage_contracts
    for name, path in locations.items():
        monkeypatch.setattr(cli, name, lambda ver=None, path=path: path)
        if hasattr(stage_contracts.paths, name):
            monkeypatch.setattr(stage_contracts.paths, name, lambda ver=None, path=path: path)
    monkeypatch.setattr(cli, "ensure_release_dirs", lambda ver: None)
    monkeypatch.setattr(cli, "find_snaps_archive", lambda path: None)
    monkeypatch.setattr(cli, "title_overrides_path", lambda: root / "optional-overrides.json")
    monkeypatch.setattr(stage_contracts, "GENRE_DESCRIPTIONS_PATH", root / "genres.json")

    args = argparse.Namespace(version="0284", json=True)
    json_code = cli.cmd_status(args)
    payload = json.loads(capsys.readouterr().out)
    assert json_code == 1
    assert all(not stage["fresh"] for stage in payload["stages"].values())

    args.json = False
    text_code = cli.cmd_status(args)
    display = capsys.readouterr().out
    assert text_code == json_code
    for name, stage in payload["stages"].items():
        state = "fresh" if stage["fresh"] else "stale"
        assert f"{name:10} : {state}" in display
