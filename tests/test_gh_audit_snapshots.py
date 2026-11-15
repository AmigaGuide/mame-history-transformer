"""Revision snapshots should be immutable and bound to source ZIP provenance."""
import json
from zipfile import ZipFile

import pytest

from mht.provenance.gh_audit_snapshots import preserve_gh_audit_snapshot


def _setup(tmp_path):
    archive = tmp_path / 'history289a.zip'
    with ZipFile(archive, 'w') as zf:
        zf.writestr('history/history.xml', '<history version="2.89a"/>')
    audit = tmp_path / 'history_audit_findings.json'
    data = {
        'schema_id': 'mht.history.audit_findings', 'schema_version': '1.0.0',
        'release': '0289', 'source': 'gaming_history',
        'detectors': {'gh.ports.odd_quotes': '1'},
        'provenance': {'inputs': [{
            'zip_archive': archive.name, 'zip_member': 'history/history.xml',
            'declared_version': '2.89a', 'declared_date': '2026-11-09',
        }]},
        'findings': [{'rule_id': 'gh.ports.odd_quotes', 'machine': 'sidearmsu',
                      'section': 'PORTS', 'source_text': '[US] PC [MS-DOS, 3.25"]'}],
    }
    audit.write_text(json.dumps(data), encoding='utf-8')
    return archive, audit, data, tmp_path / 'snapshots'


def test_creates_snapshot_with_full_audit_and_source_hash(tmp_path):
    archive, audit, data, folder = _setup(tmp_path)
    path, created = preserve_gh_audit_snapshot('0289', archive, audit, folder)
    snap = json.loads(path.read_text(encoding='utf-8'))
    assert created and path.name == 'history289a.json'
    assert snap['audit'] == data
    assert len(snap['revision_archive_sha256']) == 64
    assert snap['source_member'] == 'history/history.xml'


def test_identical_repeat_is_noop(tmp_path):
    archive, audit, _, folder = _setup(tmp_path)
    path, _ = preserve_gh_audit_snapshot('0289', archive, audit, folder)
    before = path.read_bytes()
    same, created = preserve_gh_audit_snapshot('0289', archive, audit, folder)
    assert same == path and not created and path.read_bytes() == before


def test_changed_findings_cannot_overwrite(tmp_path):
    archive, audit, data, folder = _setup(tmp_path)
    path, _ = preserve_gh_audit_snapshot('0289', archive, audit, folder)
    before = path.read_bytes()
    data['findings'].clear()
    audit.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='already exists'):
        preserve_gh_audit_snapshot('0289', archive, audit, folder)
    assert path.read_bytes() == before


def test_wrong_archive_provenance_refused_without_creating_directory(tmp_path):
    archive, audit, data, folder = _setup(tmp_path)
    data['provenance']['inputs'][0]['zip_archive'] = 'history289.zip'
    audit.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='different GH ZIP'):
        preserve_gh_audit_snapshot('0289', archive, audit, folder)
    assert not folder.exists()


def test_wrong_release_refused(tmp_path):
    archive, audit, _, folder = _setup(tmp_path)
    with pytest.raises(ValueError, match='release'):
        preserve_gh_audit_snapshot('0290', archive, audit, folder)
    assert not folder.exists()


def test_missing_member_refused(tmp_path):
    archive, audit, data, folder = _setup(tmp_path)
    data['provenance']['inputs'][0]['zip_member'] = 'missing/history.xml'
    audit.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='member missing'):
        preserve_gh_audit_snapshot('0289', archive, audit, folder)
    assert not folder.exists()


def test_modified_archive_does_not_overwrite_existing_snapshot(tmp_path):
    archive, audit, _, folder = _setup(tmp_path)
    path, _ = preserve_gh_audit_snapshot('0289', archive, audit, folder)
    before = path.read_bytes()
    with ZipFile(archive, 'w') as zf:
        zf.writestr('history/history.xml', 'changed')
    with pytest.raises(ValueError, match='already exists'):
        preserve_gh_audit_snapshot('0289', archive, audit, folder)
    assert path.read_bytes() == before


def test_bad_json_refused(tmp_path):
    archive, audit, _, folder = _setup(tmp_path)
    audit.write_text('{bad', encoding='utf-8')
    with pytest.raises(ValueError, match='Cannot read'):
        preserve_gh_audit_snapshot('0289', archive, audit, folder)
    assert not folder.exists()
