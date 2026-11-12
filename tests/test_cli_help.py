"""Regression tests for CLI help and command discoverability."""
from __future__ import annotations

import re
import sys
import json

import pytest

from mht import cli


EXPECTED_COMMANDS = (
    "diff", "run", "status", "validate", "preview", "fetch",
    "incoming", "ingest", "releases", "acquisition", "clean",
)


def _help(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["mht", *args, "--help"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    result = capsys.readouterr()
    assert not result.err
    return result.out


def test_top_level_help_prioritises_everyday_commands(monkeypatch, capsys):
    output = _help(monkeypatch, capsys)
    positions = []
    for name in EXPECTED_COMMANDS:
        match = re.search(rf"^\s{{4}}{re.escape(name)}\s", output, flags=re.MULTILINE)
        assert match is not None, f"Missing help entry for {name}"
        positions.append(match.start())
    assert positions == sorted(positions)


def test_top_level_help_contains_workflow_examples(monkeypatch, capsys):
    output = _help(monkeypatch, capsys)
    for example in (
        "python -m mht releases list",
        "python -m mht run",
        "python -m mht status --json",
        "python -m mht preview --version 0289",
    ):
        assert example in output


@pytest.mark.parametrize("command", EXPECTED_COMMANDS)
def test_existing_commands_keep_their_help(monkeypatch, capsys, command):
    output = _help(monkeypatch, capsys, command)
    assert f"mht {command}" in output


@pytest.mark.parametrize("command, option", [
    ("status", "--json"),
    ("clean", "--dry-run"),
    ("validate", "--only"),
    ("preview", "--version"),
    ("ingest", "--recover"),
])
def test_existing_command_options_remain_documented(monkeypatch, capsys, command, option):
    assert option in _help(monkeypatch, capsys, command)


def test_nested_fetch_help_remains_available(monkeypatch, capsys):
    for subcommand in ("check", "download", "snaps"):
        assert f"mht fetch {subcommand}" in _help(monkeypatch, capsys, "fetch", subcommand)


def test_no_argument_invocation_shows_help_without_processing(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["mht"])
    monkeypatch.setattr(cli, "_print_active_banner", lambda: None)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "usage: mht" in capsys.readouterr().out


def _run_cli_subprocess(args):
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-m", "mht", *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "parent, expected_usage",
    [
        (["releases"], "usage: mht releases"),
        (["fetch"], "usage: mht fetch"),
    ],
)
def test_parent_without_subcmd_prints_help_and_exits_2(
    parent, expected_usage
):
    code, output = _run_cli_subprocess(parent)
    assert code == 2
    assert expected_usage in output


def test_incoming_without_subcmd_prints_help_and_exits_0():
    code, output = _run_cli_subprocess(["incoming"])
    assert code == 0
    assert "usage: mht incoming" in output
    assert "scan" in output
    assert "adopt" in output
    assert "verify" in output


def test_diff_command_help(monkeypatch, capsys):
    output = _help(monkeypatch, capsys, "diff")

    assert "before" in output
    assert "after" in output
    assert "--json" in output


def test_diff_json_has_no_active_banner(monkeypatch, capsys):
    from mht.audit import combined_diff

    report = {
        "wiki_schema": "1.2.0",
        "counts": {"modified": 1},
    }

    monkeypatch.setattr(
        combined_diff,
        "compare_release_content",
        lambda before, after: report,
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["mht", "diff", "0288", "0289", "--json"],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0

    output = capsys.readouterr().out
    assert json.loads(output) == report


def test_diff_defaults_to_active_and_previous_release(
    monkeypatch, capsys
):
    from mht.audit import combined_diff

    calls = []

    def fake_compare(before, after):
        calls.append((before, after))
        return {"counts": {"modified": 0}}

    monkeypatch.setattr(
        combined_diff, "compare_release_content", fake_compare
    )
    monkeypatch.setattr(cli, "active_version", lambda: "0289")
    monkeypatch.setattr(
        cli,
        "list_release_versions",
        lambda: ["0287", "0289", "0288"],
    )
    monkeypatch.setattr(
        sys, "argv", ["mht", "diff", "--json"]
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    assert calls == [("0288", "0289")]
    assert json.loads(capsys.readouterr().out) == {
        "counts": {"modified": 0}
    }


def test_diff_rejects_single_release(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["mht", "diff", "0288"]
    )
    monkeypatch.setattr(
        cli, "_print_active_banner", lambda: None
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "Specify both releases" in capsys.readouterr().out


def test_diff_reports_missing_predecessor(monkeypatch, capsys):
    monkeypatch.setattr(cli, "active_version", lambda: "0288")
    monkeypatch.setattr(
        cli,
        "list_release_versions",
        lambda: ["0288", "0289"],
    )
    monkeypatch.setattr(
        cli, "_print_active_banner", lambda: None
    )
    monkeypatch.setattr(
        sys, "argv", ["mht", "diff"]
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "No preceding MAME release" in capsys.readouterr().out
