"""Selective-run behaviour without touching any real release data."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from zipfile import ZipFile

import pytest

from mht import cli, selected_run
from mht.utils.stage_contracts import StageContract
from mht.utils import paths


def _setup(monkeypatch, tmp_path, stage="history"):
    archive = tmp_path / "history.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("history.xml", b'<history version="2.89"/>')
    with ZipFile(archive) as zf:
        member = zf.getinfo("history.xml")
        record = {
            "encoding": "utf-8",
            "zip_archive": archive.name,
            "zip_member": member.filename,
            "zip_crc32": member.CRC,
            "zip_size_bytes": member.file_size,
        }
    cache = tmp_path / "encodings.json"
    cache.write_text(json.dumps({"history.xml": record, "mame.xml": {"encoding": "utf-8"}}), encoding="utf-8")
    output = tmp_path / "output.json"
    output.write_text("{}", encoding="utf-8")
    stamps = tmp_path / "stamps"
    stamps.mkdir()
    stamp = stamps / f"{stage}.json"
    stamp.write_text("{}", encoding="utf-8")
    contract = StageContract(stage, "history_parser", (archive, cache), (output,))
    monkeypatch.setattr(paths, "active_version", lambda: "0289")
    monkeypatch.setattr(paths, "stamps_dir", lambda version=None: stamps)
    monkeypatch.setattr(paths, "encodings_cache_path", lambda version=None: cache)
    monkeypatch.setattr(selected_run, "_contract", lambda name, version: contract)
    return archive, cache, output, stamp


def test_only_fresh_stage_skips_without_running(monkeypatch, tmp_path):
    _, _, _, stamp = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(selected_run, "_fresh", lambda contract, version: True)
    monkeypatch.setattr(selected_run, "_execute", lambda *args: pytest.fail("Unexpected execution"))
    assert selected_run.run_selected("history") == 0
    assert stamp.exists()


def test_only_stale_stage_executes_without_deleting_stamp(monkeypatch, tmp_path):
    _, _, _, stamp = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(selected_run, "_fresh", lambda contract, version: False)
    calls = []
    monkeypatch.setattr(selected_run, "_execute", lambda *args: calls.append(args) or True)
    assert selected_run.run_selected("history") == 0
    assert len(calls) == 1
    assert calls[0][0] == "history"
    assert stamp.exists()


def test_force_removes_selected_stamp_before_runner(monkeypatch, tmp_path):
    _, _, _, stamp = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(selected_run, "_fresh", lambda contract, version: True)
    monkeypatch.setattr(selected_run, "_execute", lambda *args: not stamp.exists())
    assert selected_run.run_selected("history", force=True) == 0
    assert not stamp.exists()  # fake runner doesn't regenerate the stamp


def test_force_does_not_invalidate_stamp_when_input_missing(monkeypatch, tmp_path):
    archive, _, _, stamp = _setup(monkeypatch, tmp_path)
    archive.unlink()
    monkeypatch.setattr(selected_run, "_execute", lambda *args: pytest.fail("Unexpected execution"))
    assert selected_run.run_selected("history", force=True) == 1
    assert stamp.exists()


def test_force_failed_runner_leaves_stage_stale(monkeypatch, tmp_path):
    _, _, _, stamp = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(selected_run, "_execute", lambda *args: False)
    assert selected_run.run_selected("history", force=True) == 1
    assert not stamp.exists()


def test_missing_encodings_does_not_invalidate_force_stamp(monkeypatch, tmp_path):
    _, cache, _, stamp = _setup(monkeypatch, tmp_path)
    cache.write_text("bad-json", encoding="utf-8")
    monkeypatch.setattr(selected_run, "_execute", lambda *args: pytest.fail("Unexpected execution"))
    assert selected_run.run_selected("history", force=True) == 1
    assert stamp.exists()


def test_transform_refuses_stale_upstream(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, stage="transform")
    monkeypatch.setattr(selected_run, "_fresh", lambda contract, version: False)
    monkeypatch.setattr(selected_run, "_execute", lambda *args: pytest.fail("Unexpected transform"))
    assert selected_run.run_selected("transform", force=True) == 1


def test_transform_with_fresh_upstream_runs(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, stage="transform")
    monkeypatch.setattr(selected_run, "_fresh", lambda contract, version: True)
    called = []
    monkeypatch.setattr(selected_run, "_execute", lambda *args: called.append(args) or True)
    assert selected_run.run_selected("transform", force=True) == 0
    assert called[0][0] == "transform"


def test_cli_rejects_force_without_stage():
    assert cli.cmd_run(argparse.Namespace(only=None, force=True)) == 2


def test_cli_dispatches_selected_stage(monkeypatch):
    monkeypatch.setattr(selected_run, "run_selected", lambda stage, force=False: 7 if (stage, force) == ("mame", True) else 9)
    assert cli.cmd_run(argparse.Namespace(only="mame", force=True)) == 7


@pytest.mark.parametrize("stage", ("ini", "mame", "history", "transform"))
def test_cli_help_mentions_stage(stage):
    proc = subprocess.run(
        [sys.executable, "-m", "mht", "run", "--help"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert stage in proc.stdout
    assert "--only" in proc.stdout
    assert "--force" in proc.stdout
