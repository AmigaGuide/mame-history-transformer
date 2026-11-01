from argparse import Namespace

from mht import cli
from mht.provenance import acquisition


def test_audit_reports_verified_archive(monkeypatch, capsys):
    def fake_audit(release, *, check_integrity):
        assert release == "0289"
        assert check_integrity is True

        return [{
            "filename": "mame0289lx.zip",
            "source_type": "mame",
            "verification_status": "verified",
            "sha256": "example-sha256",
            "embedded_metadata": {
                "embedded_version": "0.289 (mame0289)",
                "embedded_date": None,
                "error": None,
            },
            "integrity_verification": {
                "status": "passed",
                "error": None,
            },
        }]

    monkeypatch.setattr(
        acquisition,
        "audit_release_archives",
        fake_audit,
    )

    result = cli.cmd_acquisition_audit(
        Namespace(version="0289")
    )

    output = capsys.readouterr().out

    assert result == 0
    assert "mame0289lx.zip" in output
    assert "0.289 (mame0289)" in output
    assert "1 verified" in output


def test_audit_reports_failed_archive(monkeypatch, capsys):
    monkeypatch.setattr(
        acquisition,
        "audit_release_archives",
        lambda release, *, check_integrity: [{
            "filename": "history289.zip",
            "source_type": "gaming_history",
            "verification_status": "mismatch",
            "sha256": "example-sha256",
            "embedded_metadata": {
                "embedded_version": "2.88",
                "embedded_date": None,
                "error": None,
            },
            "integrity_verification": {
                "status": "passed",
                "error": None,
            },
        }],
    )

    result = cli.cmd_acquisition_audit(
        Namespace(version="0289")
    )

    assert result == 1
    assert "1 requiring attention" in capsys.readouterr().out


def test_audit_reports_missing_archives(monkeypatch, capsys):
    monkeypatch.setattr(
        acquisition,
        "audit_release_archives",
        lambda release, *, check_integrity: [],
    )

    result = cli.cmd_acquisition_audit(
        Namespace(version="0289")
    )

    assert result == 1
    assert "No ZIP archives found" in capsys.readouterr().out
