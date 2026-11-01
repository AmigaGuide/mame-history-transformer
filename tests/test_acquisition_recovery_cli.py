from argparse import Namespace

from mht import cli
from mht.provenance import acquisition


def make_args(version="0289", recover=True):
    return Namespace(
        version=version,
        incoming=None,
        recover=recover,
    )


import pytest


@pytest.fixture(autouse=True)
def no_stranded_records(monkeypatch):
    """
    Keep existing CLI tests focused on staged recovery.
    """
    monkeypatch.setattr(
        acquisition,
        "recover_stranded_acquisitions",
        lambda release, *, incoming_directory: [],
    )


def test_recovery_requires_explicit_release():
    result = cli.cmd_ingest(make_args(version=None))

    assert result == 2


def test_recovery_reports_no_pending_records(
    monkeypatch,
    capsys,
):
    def fake_recover(release):
        assert release == "0289"
        return []

    monkeypatch.setattr(
        acquisition,
        "recover_staged_acquisitions",
        fake_recover,
    )

    assert cli.cmd_ingest(make_args()) == 0
    assert "No pending staged acquisitions" in capsys.readouterr().out


def test_recovery_reports_success(monkeypatch, capsys):
    monkeypatch.setattr(
        acquisition,
        "recover_staged_acquisitions",
        lambda release: [{
            "filename": "pS_CatVer_289.zip",
            "release": release,
            "action": "recovered",
            "acquisition_manifest": (
                "data/releases/0289/acquisition_manifest.json"
            ),
        }],
    )

    assert cli.cmd_ingest(make_args()) == 0

    output = capsys.readouterr().out
    assert "[RECOVERED] pS_CatVer_289.zip" in output
    assert "recovered=1 errors=0" in output


def test_recovery_reports_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        acquisition,
        "recover_staged_acquisitions",
        lambda release: [{
            "filename": "pS_CatVer_289.zip",
            "release": release,
            "action": "error",
            "error": "Simulated pending record failure",
        }],
    )

    assert cli.cmd_ingest(make_args()) == 1
    assert "Simulated pending record failure" in capsys.readouterr().out


def test_recovery_combines_stranded_and_staged_results(
    monkeypatch,
    capsys,
):
    calls = []

    def fake_stranded(release, *, incoming_directory):
        calls.append("stranded")
        assert release == "0289"
        return [{
            "filename": "history289.zip",
            "release": release,
            "action": "recovered",
            "acquisition_manifest": "manifest.json",
        }]

    def fake_staged(release):
        calls.append("staged")
        return [{
            "filename": "pS_CatVer_289.zip",
            "release": release,
            "action": "recovered",
            "acquisition_manifest": "manifest.json",
        }]

    monkeypatch.setattr(
        acquisition,
        "recover_stranded_acquisitions",
        fake_stranded,
    )
    monkeypatch.setattr(
        acquisition,
        "recover_staged_acquisitions",
        fake_staged,
    )

    assert cli.cmd_ingest(make_args()) == 0

    output = capsys.readouterr().out

    assert calls == ["stranded", "staged"]
    assert "[RECOVERED] history289.zip" in output
    assert "[RECOVERED] pS_CatVer_289.zip" in output
    assert "recovered=2 errors=0" in output


def test_recovery_preserves_failure_exit_status(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        acquisition,
        "recover_stranded_acquisitions",
        lambda release, *, incoming_directory: [{
            "filename": "history289.zip",
            "action": "error",
            "error": "SHA-256 mismatch",
        }],
    )

    monkeypatch.setattr(
        acquisition,
        "recover_staged_acquisitions",
        lambda release: [{
            "filename": "pS_CatVer_289.zip",
            "action": "recovered",
            "acquisition_manifest": "manifest.json",
        }],
    )

    assert cli.cmd_ingest(make_args()) == 1

    output = capsys.readouterr().out

    assert "SHA-256 mismatch" in output
    assert "recovered=1 errors=1" in output
