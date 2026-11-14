"""Regression coverage for safe, isolated Gaming History revision acquisition."""
from pathlib import Path

import pytest

from mht.provenance.gh_revisions import download_advertised_gh_revision


def sample(status='update_available', release='0289', revision='a'):
    return {'release': release, 'status': status,
            'advertised': {'release': release, 'revision': revision,
                           'filename': f'history{int(release)}{revision}.zip'}}


def test_plan_does_not_download(tmp_path):
    calls = []
    result = download_advertised_gh_revision('0289', destination_dir=tmp_path,
        checker=lambda _: sample(), downloader=lambda *a, **kw: calls.append(a))
    assert result['action'] == 'planned'
    assert result['filename'] == 'history289a.zip'
    assert result['url'] == 'https://www.arcade-history.com/dats/history289a.zip'
    assert calls == [] and not list(tmp_path.iterdir())


@pytest.mark.parametrize('status', ['up_to_date', 'local_newer', 'website_older', 'different_release'])
def test_no_download_if_advertisement_not_newer(tmp_path, status):
    result = download_advertised_gh_revision('0289', yes=True, destination_dir=tmp_path,
        checker=lambda _: sample(status), downloader=lambda *a, **k: pytest.fail('unexpected download'))
    assert result['action'] == 'skipped'


def test_new_revision_uses_verified_downloader_without_overwrite(tmp_path):
    seen = []
    def downloader(url, dest, *, overwrite):
        seen.append((url, dest, overwrite))
        return {'ok': True, 'sha256': 'abc'}
    result = download_advertised_gh_revision('0289', yes=True,
        destination_dir=tmp_path, checker=lambda _: sample(), downloader=downloader)
    assert result['action'] == 'downloaded'
    assert seen == [('https://www.arcade-history.com/dats/history289a.zip',
                     tmp_path / 'history289a.zip', False)]


def test_existing_incoming_file_is_not_replaced(tmp_path):
    result = download_advertised_gh_revision('0289', yes=True,
        destination_dir=tmp_path, checker=lambda _: sample(),
        downloader=lambda *a, **k: {'ok': True, 'reason': 'exists', 'sha256': 'abc'})
    assert result['action'] == 'existing'


def test_failed_validation_does_not_claim_success(tmp_path):
    result = download_advertised_gh_revision('0289', yes=True,
        destination_dir=tmp_path, checker=lambda _: sample(),
        downloader=lambda *a, **k: {'ok': False, 'reason': 'invalid_existing_archive', 'error': 'Invalid ZIP'})
    assert not result['ok'] and result['action'] == 'error'


def test_unexpected_filename_is_rejected(tmp_path):
    report = sample()
    report['advertised']['filename'] = '../../history289a.zip'
    result = download_advertised_gh_revision('0289', yes=True,
        destination_dir=tmp_path, checker=lambda _: report,
        downloader=lambda *a, **k: pytest.fail('unexpected download'))
    assert result['action'] == 'blocked'


def test_embedded_release_mismatch_is_rejected(tmp_path):
    report = sample()
    report['advertised']['release'] = '0290'
    result = download_advertised_gh_revision('0289', yes=True,
        destination_dir=tmp_path, checker=lambda _: report,
        downloader=lambda *a, **k: pytest.fail('unexpected download'))
    assert result['reason'] == 'release_mismatch'


def test_parser_has_gh_download_command():
    from mht.cli import cmd_fetch_gh_download
    assert callable(cmd_fetch_gh_download)


def test_changed_advertisement_is_blocked(tmp_path):
    result = download_advertised_gh_revision('0289', yes=True, expected_filename='history289a.zip',
        destination_dir=tmp_path, checker=lambda _: sample(revision='b'),
        downloader=lambda *a, **k: pytest.fail('unexpected download'))
    assert result['action'] == 'blocked'
    assert result['reason'] == 'advertisement_changed'
