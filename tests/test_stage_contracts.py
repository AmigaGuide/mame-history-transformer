"""Regression tests for the centralised stage stamp contracts."""
from __future__ import annotations

from pathlib import Path

import pytest

from mht.utils import stage_contracts


@pytest.fixture
def release_paths(tmp_path, monkeypatch):
    """Provide deterministic paths without modifying a real release."""
    root = tmp_path / 'release'
    names = {
        'encodings_cache_path': 'encodings.json',
        'mame_xml_path': 'extracted/mame.xml',
        'ini_classifications_path': 'outputs/gh_ini_classifications.json',
        'ini_summary_path': 'summaries/ini_parsing_summary.json',
        'mame_machines_path': 'outputs/mame_machines.json',
        'parent_index_path': 'outputs/mame_parent_index.json',
        'mame_summary_path': 'summaries/mame_parsing_summary.json',
        'gh_system_ports_path': 'outputs/gh_system_ports.json',
        'gh_system_trivia_path': 'outputs/gh_system_trivia.json',
        'history_summary_path': 'summaries/history_parsing_summary.json',
        'exotica_wiki_path': 'outputs/exotica_lit_wiki.json',
        'exotica_raw_path': 'outputs/exotica_lit_raw_data.json',
        'exotica_pages_path': 'outputs/exotica_wiki_pages_and_redirects.json',
        'transform_summary_path': 'summaries/transform_summary.json',
    }
    loc = {key: root / value for key, value in names.items()}
    for key, path in loc.items():
        monkeypatch.setattr(stage_contracts.paths, key, lambda version=None, path=path: path)
    loc['title_overrides_path'] = tmp_path / 'overrides.json'
    monkeypatch.setattr(stage_contracts.paths, 'title_overrides_path',
                        lambda: loc['title_overrides_path'])
    loc['genres'] = tmp_path / 'genres.json'
    monkeypatch.setattr(stage_contracts, 'GENRE_DESCRIPTIONS_PATH', loc['genres'])
    return loc


def test_ini_contract_uses_history_zip_and_declares_two_outputs(release_paths, tmp_path):
    source = tmp_path / 'history.zip'
    contract = stage_contracts.stage_contract('ini', '0289', source=source)
    assert contract.tool == 'ini_summary'
    assert contract.schema_id == 'mht.stage.ini'
    assert contract.stamp_filename == 'ini.json'
    assert contract.inputs == (source, release_paths['encodings_cache_path'])
    assert contract.outputs == (
        release_paths['ini_classifications_path'], release_paths['ini_summary_path'])
    assert not contract.missing_source


def test_history_contract_keeps_trivia_as_required_output(release_paths, tmp_path):
    source = tmp_path / 'history.zip'
    contract = stage_contracts.stage_contract('history', '0289', source=source)
    assert contract.inputs == (source, release_paths['encodings_cache_path'])
    assert release_paths['gh_system_trivia_path'] in contract.outputs
    assert len(contract.outputs) == 3


def test_mame_contract_uses_extracted_fallback(release_paths):
    contract = stage_contracts.stage_contract('mame', '0289')
    assert contract.inputs[0] == release_paths['mame_xml_path']
    assert not contract.missing_source
    assert len(contract.outputs) == 3


def test_missing_history_source_is_explicit(release_paths):
    for name in ('ini', 'history'):
        contract = stage_contracts.stage_contract(name, '0289')
        assert contract.missing_source
        assert contract.inputs == (release_paths['encodings_cache_path'],)


def test_transform_contract_preserves_dependency_order(release_paths, tmp_path):
    snaps = tmp_path / 'snaps.zip'
    contract = stage_contracts.stage_contract('transform', '0289', snaps_archive=snaps)
    assert contract.inputs == (
        release_paths['mame_machines_path'],
        release_paths['ini_classifications_path'],
        release_paths['parent_index_path'],
        release_paths['gh_system_ports_path'],
        release_paths['mame_summary_path'],
        release_paths['history_summary_path'],
        release_paths['ini_summary_path'],
        release_paths['title_overrides_path'],
        release_paths['genres'],
        snaps,
    )
    assert contract.optional_inputs == (release_paths['title_overrides_path'],)
    assert len(contract.outputs) == 4
    assert not contract.missing_source


def test_transform_requires_snaps(release_paths):
    contract = stage_contracts.stage_contract('transform', '0289')
    assert contract.missing_source
    assert len(contract.inputs) == 9


def test_unknown_stage_is_rejected(release_paths):
    with pytest.raises(ValueError, match='Unknown stage'):
        stage_contracts.stage_contract('bad-name', '0289')
