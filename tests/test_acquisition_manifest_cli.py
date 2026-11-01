from argparse import Namespace

from mht import cli
from mht.provenance import acquisition


def test_manifest_command_reports_success(
    monkeypatch,
    tmp_path,
    capsys,
):
    expected = tmp_path / "acquisition_manifest.json"
    calls = []

    def fake_save(release):
        calls.append(release)
        return expected

    monkeypatch.setattr(
        acquisition,
        "save_acquisition_manifest",
        fake_save,
    )

    result = cli.cmd_acquisition_manifest(
        Namespace(version="0289")
    )

    assert result == 0
    assert calls == ["0289"]
    assert str(expected) in capsys.readouterr().out


def test_manifest_command_reports_verification_failure(
    monkeypatch,
    capsys,
):
    def fake_save(release):
        raise ValueError("archive verification incomplete")

    monkeypatch.setattr(
        acquisition,
        "save_acquisition_manifest",
        fake_save,
    )

    result = cli.cmd_acquisition_manifest(
        Namespace(version="0289")
    )

    assert result == 1
    assert (
        "archive verification incomplete"
        in capsys.readouterr().out
    )
