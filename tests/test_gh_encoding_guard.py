import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from mht.utils import gh_encoding_guard as guard


def _fixture(tmp_path, names=('history.xml', '[GAMING HISTORY] Game Or No Game.ini', '[GAMING HISTORY] Machine Type.ini')):
    archive = tmp_path / 'history289a.zip'
    with ZipFile(archive, 'w') as zf:
        for name in names:
            zf.writestr(name, b'hello')
    with ZipFile(archive) as zf:
        records = {
            Path(m.filename).name: {
                'zip_archive': archive.name,
                'zip_member': m.filename,
                'zip_crc32': m.CRC,
                'zip_size_bytes': m.file_size,
                'encoding': 'utf-8',
            }
            for m in zf.infolist()
        }
    cache_path = tmp_path / 'encodings.json'
    cache_path.write_text(json.dumps(records), encoding='utf-8')
    return archive, cache_path, records


def test_current_xml_and_ini_accepted(tmp_path, monkeypatch):
    archive, cache, _ = _fixture(tmp_path)
    monkeypatch.setattr(guard, 'encodings_cache_path', lambda v: cache)
    guard.check_gh_encoding_cache('0289', archive, 'history')
    guard.check_gh_encoding_cache('0289', archive, 'ini')


def test_old_archive_name_rejected(tmp_path, monkeypatch):
    archive, cache, records = _fixture(tmp_path)
    records['history.xml']['zip_archive'] = 'history289.zip'
    cache.write_text(json.dumps(records), encoding='utf-8')
    monkeypatch.setattr(guard, 'encodings_cache_path', lambda v: cache)
    with pytest.raises(ValueError, match='Stale encoding provenance'):
        guard.check_gh_encoding_cache('0289', archive, 'history')


def test_changed_member_crc_rejected(tmp_path, monkeypatch):
    archive, cache, records = _fixture(tmp_path)
    records['[GAMING HISTORY] Machine Type.ini']['zip_crc32'] ^= 1
    cache.write_text(json.dumps(records), encoding='utf-8')
    monkeypatch.setattr(guard, 'encodings_cache_path', lambda v: cache)
    with pytest.raises(ValueError, match='Stale encoding provenance'):
        guard.check_gh_encoding_cache('0289', archive, 'ini')


def test_missing_optional_ini_allowed(tmp_path, monkeypatch):
    archive, cache, _ = _fixture(tmp_path)
    monkeypatch.setattr(guard, 'encodings_cache_path', lambda v: cache)
    guard.check_gh_encoding_cache('0289', archive, 'ini')


def test_missing_history_xml_rejected(tmp_path, monkeypatch):
    archive, cache, _ = _fixture(tmp_path, names=('[GAMING HISTORY] Machine Type.ini',))
    monkeypatch.setattr(guard, 'encodings_cache_path', lambda v: cache)
    with pytest.raises(ValueError, match='Missing history.xml'):
        guard.check_gh_encoding_cache('0289', archive, 'history')


def test_obsolete_optional_ini_record_rejected(tmp_path, monkeypatch):
    archive, cache, records = _fixture(tmp_path)
    records['[GAMING HISTORY] Machine Category.ini'] = dict(records['history.xml'])
    cache.write_text(json.dumps(records), encoding='utf-8')
    monkeypatch.setattr(guard, 'encodings_cache_path', lambda v: cache)
    with pytest.raises(ValueError, match='still records absent INI'):
        guard.check_gh_encoding_cache('0289', archive, 'ini')


def test_invalid_cache_rejected(tmp_path, monkeypatch):
    archive, cache, _ = _fixture(tmp_path)
    cache.write_text('{not json', encoding='utf-8')
    monkeypatch.setattr(guard, 'encodings_cache_path', lambda v: cache)
    with pytest.raises(ValueError, match='Cannot read encoding cache'):
        guard.check_gh_encoding_cache('0289', archive, 'history')


def test_mismatched_member_path_rejected(tmp_path, monkeypatch):
    archive, cache, records = _fixture(tmp_path)
    records['history.xml']['zip_member'] = 'previous/history.xml'
    cache.write_text(json.dumps(records), encoding='utf-8')
    monkeypatch.setattr(guard, 'encodings_cache_path', lambda v: cache)
    with pytest.raises(ValueError, match='Stale encoding provenance'):
        guard.check_gh_encoding_cache('0289', archive, 'history')
