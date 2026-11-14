"""Read-only GH revision discovery tests; all HTTP requests are mocked."""
import argparse
import pytest

from mht.provenance import gh_revisions as gh
from mht import cli


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, page):
        self.page = page
        self.calls = []

    def get(self, url, *, timeout):
        self.calls.append((url, timeout))
        return FakeResponse(self.page)


def test_modern_page_identifies_latest_not_previous():
    html = '<h2>Latest version</h2><p>v2.89a Released November 9, 2026</p><h3>Previous versions</h3><p>v2.89</p>'
    assert gh.advertised_history(html) == {'release': '0289', 'revision': 'a', 'filename': 'history289a.zip'}


def test_legacy_page():
    assert gh.advertised_history('<a>Download Ver. 2.89</a>') == {
        'release': '0289', 'revision': '', 'filename': 'history289.zip'}


def test_latest_label_not_found_fails_closed():
    with pytest.raises(ValueError, match='Could not identify'):
        gh.advertised_history('<p>Previous versions v2.89a v2.89</p>')


def test_staged_highest_revision_only_and_release_isolated(tmp_path):
    for filename in ('history289.zip', 'history289a.zip', 'history289b.zip', 'history288c.zip', 'history289__dup1.zip'):
        (tmp_path / filename).write_bytes(b'x')
    assert gh.staged_history('0289', directory=tmp_path) == {
        'filename': 'history289b.zip', 'revision': 'b'}


def test_update_available_does_not_download_or_write(tmp_path):
    (tmp_path / 'history289.zip').write_bytes(b'original')
    session = FakeSession('<h2>Latest version</h2>v2.89a')
    before = set(tmp_path.iterdir())
    result = gh.check_gh_revision('0289', session=session, directory=tmp_path)
    assert result['status'] == 'update_available'
    assert session.calls == [(gh.GH_DOWNLOAD_PAGE, 15.0)]
    assert set(tmp_path.iterdir()) == before
    assert (tmp_path / 'history289.zip').read_bytes() == b'original'


def test_matching_revision(tmp_path):
    (tmp_path / 'history289a.zip').write_bytes(b'x')
    result = gh.check_gh_revision('0289', session=FakeSession('Latest version v2.89a'), directory=tmp_path)
    assert result['status'] == 'up_to_date'


def test_newer_base_release_is_not_misreported_as_update(tmp_path):
    (tmp_path / 'history288.zip').write_bytes(b'x')
    result = gh.check_gh_revision('0288', session=FakeSession('Latest version v2.89a'), directory=tmp_path)
    assert result['status'] == 'different_release'


def test_local_revision_later_than_site(tmp_path):
    (tmp_path / 'history289b.zip').write_bytes(b'x')
    result = gh.check_gh_revision('0289', session=FakeSession('Latest version v2.89a'), directory=tmp_path)
    assert result['status'] == 'local_newer'


def test_cli_command_json(monkeypatch, capsys):
    monkeypatch.setattr(gh, 'check_gh_revision', lambda version: {
        'release': '0289', 'staged': {'filename': 'history289.zip', 'revision': ''},
        'advertised': {'release': '0289', 'revision': 'a', 'filename': 'history289a.zip'},
        'status': 'update_available', 'source': gh.GH_DOWNLOAD_PAGE})
    assert cli.cmd_fetch_gh_check(argparse.Namespace(version='0289', json=True)) == 0
    assert 'history289a.zip' in capsys.readouterr().out


def test_cli_command_network_failure(monkeypatch, capsys):
    def fail(_):
        raise ValueError('Unrecognised page')
    monkeypatch.setattr(gh, 'check_gh_revision', fail)
    assert cli.cmd_fetch_gh_check(argparse.Namespace(version='0289', json=False)) == 1
    assert 'Unrecognised page' in capsys.readouterr().out
