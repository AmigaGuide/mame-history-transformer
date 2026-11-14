"""Regression checks for authoritative GH ZIP selection (read-only)."""
from pathlib import Path

import pytest

from mht.provenance.gh_archive_selection import select_history_archive


def put(folder: Path, *names: str):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b'example')


def test_highest_revision_wins_regardless_of_file_order(tmp_path):
    put(tmp_path, 'history289b.zip', 'history289.zip', 'history289a.zip')
    assert select_history_archive('0289', directory=tmp_path).name == 'history289b.zip'


def test_base_release_is_usable(tmp_path):
    put(tmp_path, 'history289.zip')
    assert select_history_archive('0289', directory=tmp_path).name == 'history289.zip'


def test_does_not_cross_mame_release_or_pick_other_archives(tmp_path):
    put(tmp_path, 'history288z.zip', 'mame0289lx.zip', 'ps_catver_289.zip')
    assert select_history_archive('0289', directory=tmp_path) is None


def test_unknown_history_names_are_not_authoritative(tmp_path):
    put(tmp_path, 'history289__dup1.zip', 'some_history289.zip', 'history289aa.zip')
    assert select_history_archive('0289', directory=tmp_path) is None


def test_missing_directory_is_read_only(tmp_path):
    folder = tmp_path / 'absent'
    assert select_history_archive('0289', directory=folder) is None
    assert not folder.exists()


def test_case_insensitive_filename_with_single_source(tmp_path):
    put(tmp_path, 'HISTORY289A.ZIP')
    assert select_history_archive('0289', directory=tmp_path).name == 'HISTORY289A.ZIP'


def test_duplicate_revision_is_rejected(tmp_path):
    put(tmp_path, 'history289a.zip', 'HISTORY289A.ZIP')
    # NTFS is case-insensitive; on Windows the second file replaces the first.
    if len(list(tmp_path.iterdir())) < 2:
        pytest.skip('case-insensitive filesystem')
    with pytest.raises(ValueError, match='Ambiguous'):
        select_history_archive('0289', directory=tmp_path)


@pytest.mark.parametrize('bad', ['0289a', '289', '../0289', ''])
def test_invalid_release_key_rejected(tmp_path, bad):
    with pytest.raises(ValueError, match='four-digit'):
        select_history_archive(bad, directory=tmp_path)


def test_history_and_ini_parsers_share_selection(tmp_path, monkeypatch):
    from mht.inputs import history_ini_parser, history_xml_parser
    from mht.provenance import gh_archive_selection as selection
    put(tmp_path, 'history289.zip', 'history289a.zip')
    monkeypatch.setattr(selection, 'archives_dir', lambda version: tmp_path)
    assert history_ini_parser._pick_history_zip('0289').name == 'history289a.zip'
    assert history_xml_parser._pick_history_zip('0289').name == 'history289a.zip'


def test_selected_run_uses_authoritative_source(tmp_path, monkeypatch):
    from mht.selected_run import _contract
    from mht.provenance import gh_archive_selection as selection
    put(tmp_path, 'history289.zip', 'history289a.zip')
    monkeypatch.setattr(selection, 'archives_dir', lambda version: tmp_path)
    assert _contract('ini', '0289').inputs[0].name == 'history289a.zip'
    assert _contract('history', '0289').inputs[0].name == 'history289a.zip'


def test_cli_status_uses_authoritative_source(tmp_path, monkeypatch):
    import argparse
    import mht.cli as cli
    from mht.provenance import gh_archive_selection as selection
    put(tmp_path, 'history289.zip', 'history289a.zip')
    monkeypatch.setattr(selection, 'archives_dir', lambda version: tmp_path)
    monkeypatch.setattr(cli, 'ensure_release_dirs', lambda version: None)
    monkeypatch.setattr(cli, 'archives_dir', lambda version: tmp_path)
    sources = {}
    def contract(stage, version, **kwargs):
        sources[stage] = kwargs.get('source')
        from mht.utils.stage_contracts import stage_contract
        return stage_contract(stage, version, **kwargs)
    monkeypatch.setattr(cli, 'stage_contract', contract)
    cli.cmd_status(argparse.Namespace(version='0289', json=True))
    assert sources['history'].name == 'history289a.zip'
    assert sources['ini'].name == 'history289a.zip'
