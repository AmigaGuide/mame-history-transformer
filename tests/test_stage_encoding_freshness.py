"""Regression coverage for stage-specific encoding freshness and old stamp migration."""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from mht.utils import stamps
from mht.utils.encoding_stamp import semantic_cache_signature
import hashlib


def _legacy_digest(doc):
    basis = {'stage_id': doc['stage_id'], 'tool_version': doc['tool_version'],
             'inputs': [dict(path=i['path'], size=i['size'], mtime_ns=i['mtime_ns']) for i in doc['inputs']],
             'extra': doc.get('extra')}
    return hashlib.sha256(json.dumps(basis, ensure_ascii=False, separators=(',', ':'),
                                     sort_keys=True).encode('utf-8')).hexdigest()


def _fixture(tmp_path: Path):
    source = tmp_path / 'history289.zip'
    with ZipFile(source, 'w') as zf:
        zf.writestr('history.xml', b'<history/>')
        zf.writestr('[GAMING HISTORY] Game Or No Game.ini', b'[game]\n')
    with ZipFile(source) as zf:
        h = zf.getinfo('history.xml')
        g = zf.getinfo('[GAMING HISTORY] Game Or No Game.ini')
    def rec(member, info):
        return dict(encoding='utf-8', zip_archive=source.name, zip_member=member,
                    zip_crc32=info.CRC, zip_size_bytes=info.file_size)
    cache = tmp_path/'encodings.json'
    data = {'history.xml': rec('history.xml', h),
            '[GAMING HISTORY] Game Or No Game.ini': rec(g.filename, g),
            'mame.xml': dict(rec('history.xml', h), zip_archive='mame0289lx.zip')}
    cache.write_text(json.dumps(data), encoding='utf-8')
    return source, cache, data


def test_unrelated_gh_changes_do_not_change_mame_fingerprint(tmp_path):
    _, cache, data = _fixture(tmp_path)
    before = semantic_cache_signature('mht.stage.mame', cache)
    data['history.xml']['zip_archive'] = 'history289a.zip'
    cache.write_text(json.dumps(data), encoding='utf-8')
    assert semantic_cache_signature('mht.stage.mame', cache) == before


def test_gh_change_invalidates_history_not_ini(tmp_path):
    _, cache, data = _fixture(tmp_path)
    h_before = semantic_cache_signature('mht.stage.history', cache)
    i_before = semantic_cache_signature('mht.stage.ini', cache)
    data['history.xml']['zip_crc32'] += 1
    cache.write_text(json.dumps(data), encoding='utf-8')
    assert semantic_cache_signature('mht.stage.history', cache) != h_before
    assert semantic_cache_signature('mht.stage.ini', cache) == i_before


def test_ini_change_invalidates_ini_not_history(tmp_path):
    _, cache, data = _fixture(tmp_path)
    h_before = semantic_cache_signature('mht.stage.history', cache)
    i_before = semantic_cache_signature('mht.stage.ini', cache)
    data['[GAMING HISTORY] Game Or No Game.ini']['encoding'] = 'windows-1252'
    cache.write_text(json.dumps(data), encoding='utf-8')
    assert semantic_cache_signature('mht.stage.ini', cache) != i_before
    assert semantic_cache_signature('mht.stage.history', cache) == h_before


def test_volatile_cache_fields_do_not_invalidate(tmp_path):
    _, cache, data = _fixture(tmp_path)
    before = semantic_cache_signature('mht.stage.history', cache)
    data['history.xml']['detected_at_utc'] = 'later'
    cache.write_text(json.dumps(data), encoding='utf-8')
    assert semantic_cache_signature('mht.stage.history', cache) == before


def test_malformed_cache_fails_closed(tmp_path):
    cache=tmp_path/'encodings.json'
    cache.write_text('{bad', encoding='utf-8')
    assert semantic_cache_signature('mht.stage.history', cache) == 'invalid-cache'


def test_new_stage_stamp_unaffected_by_unrelated_cache_edit(tmp_path, monkeypatch):
    source, cache, data = _fixture(tmp_path)
    monkeypatch.setattr(stamps, 'tool_version', lambda tool: 'test')
    sdir = tmp_path/'stamps'
    sdir.mkdir()
    inputs=[source,cache]
    before=stamps.make_stamp('mht.stage.mame','test',inputs)
    stamps.save_stamp(sdir/'mame.json',before)
    data['history.xml']['zip_archive']='history289a.zip'
    cache.write_text(json.dumps(data),encoding='utf-8')
    fresh, _, _ = stamps.stage_is_fresh('mame.json',schema_id='mht.stage.mame',
        tool='mame_parser', inputs=inputs, stamps_dir=sdir)
    assert fresh


def test_legacy_history_stamp_reused_with_identical_cache(tmp_path, monkeypatch):
    source, cache, data = _fixture(tmp_path)
    monkeypatch.setattr(stamps, 'tool_version', lambda tool: 'test')
    sdir=tmp_path/'stamps';sdir.mkdir()
    inputs=[source,cache]
    current=stamps.make_stamp('mht.stage.history','test',inputs)
    legacy=dict(current)
    legacy['inputs_detail']=[dict(leaf='history.xml',**data['history.xml'])]
    legacy['digest']=_legacy_digest(legacy)
    stamps.save_stamp(sdir/'history.json',legacy)
    fresh,_,_=stamps.stage_is_fresh('history.json',schema_id='mht.stage.history',
       tool='history_parser',inputs=inputs,stamps_dir=sdir)
    assert fresh


def test_legacy_stamp_rejects_encoding_change(tmp_path, monkeypatch):
    source,cache,data=_fixture(tmp_path)
    monkeypatch.setattr(stamps,'tool_version',lambda tool:'test')
    sdir=tmp_path/'stamps';sdir.mkdir()
    inputs=[source,cache]
    legacy=stamps.make_stamp('mht.stage.history','test',inputs)
    legacy['inputs_detail']=[dict(leaf='history.xml',**data['history.xml'])]
    legacy['digest']=_legacy_digest(legacy)
    stamps.save_stamp(sdir/'history.json',legacy)
    data['history.xml']['encoding']='windows-1252'
    cache.write_text(json.dumps(data),encoding='utf-8')
    fresh,_,_=stamps.stage_is_fresh('history.json',schema_id='mht.stage.history',
       tool='history_parser',inputs=inputs,stamps_dir=sdir)
    assert not fresh
