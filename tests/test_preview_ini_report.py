"""Phase 10D: INI report shape and rendered HTML regressions."""
from __future__ import annotations

from mht.preview.ini_report import build_ini_report
from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData


def _data(ini_summary):
    return PreviewData(wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
                       mame_summary={}, history_summary={}, ini_summary=ini_summary,
                       transform_summary={}, machine_order=[])


def test_coverage_preserves_explicit_zero_and_missing():
    report = build_ini_report({'totals': {'unique_machine_names_union': 9,
                                          'missing_in_category': 0}})
    assert [(r['label'], r['value']) for r in report['coverage']] == [
        ('Distinct machine names across all three INIs', 9),
        ('Missing machine category', 0),
    ]


def test_coverage_does_not_treat_boolean_as_integer():
    assert build_ini_report({'totals': {'missing_in_type': True}})['coverage'] == []


def test_three_files_have_stable_names_without_fabricated_source_paths():
    report = build_ini_report({'ini': {'files': {'game_status': {'filename': 'game_status'}}}})
    assert [f['friendly_filename'] for f in report['files']] == [
        'Game Or No Game.ini', 'Machine Category.ini', 'Machine Type.ini']
    assert report['files'][0]['source_filename'] is None
    assert report['files'][1]['source_filename'] is None


def test_source_zip_and_declared_per_file_mame_version():
    summary = {'provenance': {'inputs': [{'zip_member': 'folder/Gaming INI.ini',
        'zip_archive': 'history289.zip', 'declared_mame_version': '0.288'}]}}
    card = build_ini_report(summary)['files'][0]
    assert (card['source_filename'], card['archive'], card['mame_version']) == (
        'folder/Gaming INI.ini', 'history289.zip', '0.288')


def test_classifications_are_sorted_and_bounded_to_twelve():
    sections = {f'section {i}': i for i in range(20)}
    report = build_ini_report({'ini': {'files': {'type': {
        'section_counts_listed': sections}}}})
    ranked = report['files'][2]['listed']
    assert ranked['total_groups'] == 20
    assert len(ranked['rows']) == 12
    assert ranked['rows'][0] == {'name': 'section 19', 'count': 19}


def test_unique_and_listed_counts_are_not_conflated():
    report = build_ini_report({'ini': {'files': {'category': {
        'section_counts_listed': {'Arcade': 10},
        'section_counts_unique': {'Arcade': 7}}}}})
    card = report['files'][1]
    assert card['listed']['rows'][0]['count'] == 10
    assert card['unique']['rows'][0]['count'] == 7


def test_nonzero_duplicates_are_observations_but_zeros_are_not():
    report = build_ini_report({'ini': {'files': {'game_status': {
        'machines_with_multiple_sections': 3, 'duplicate_assignments': 0}}}})
    assert len(report['observations']) == 1
    assert report['observations'][0]['count'] == 3
    assert report['observations'][0]['path'] == 'ini.files.game_status.machines_with_multiple_sections'


def test_errors_are_counted_without_exposing_full_messages():
    r = build_ini_report({'errors': ['UNIQUE_ERROR_MARKER', 'second error']})
    assert r['observations'][-1]['count'] == 2
    assert r['observations'][-1]['path'] == 'errors'


def test_source_record_does_not_mutate_input():
    summary = {'ini': {'files': {'type': {'section_counts_listed': {'Console': 5}}}}}
    import copy
    before = copy.deepcopy(summary)
    build_ini_report(summary)
    assert summary == before


def test_rendered_ini_summary_is_bounded_and_links_to_diagnostics():
    summary = {'header': {'versions': {'mame_xml_version': '0.289'}},
      'ini': {'files': {'game_status': {'filename': 'Game Or No Game.ini',
       'version': {'mame_version': '0.289', 'unknown_key': 'SHOULD_NOT_RENDER'},
       'section_counts_listed': {f'category {x}': x for x in range(20)}}}},
      'totals': {'unique_machine_names_union': 999},
      'sentinel': 'SOURCE_JSON_ONLY_MARKER'}
    app = create_app(_data(summary), version='0289')
    app.config.update(TESTING=True)
    html = app.test_client().get('/summary/ini').get_data(as_text=True)
    assert 'ini_parsing_summary.json' in html
    assert 'Distinct machine names across all three INIs' in html
    assert 'category 19' in html and 'category 0' not in html
    assert 'SHOULD_NOT_RENDER' not in html
    assert 'SOURCE_JSON_ONLY_MARKER' not in html
    assert '/diagnostics' in html
    assert '/summary/ini/source.json' in html
    assert "'mame_version':" not in html


def test_empty_summary_is_safe_to_render():
    app = create_app(_data({}), version='0289')
    app.config.update(TESTING=True)
    result = app.test_client().get('/summary/ini')
    assert result.status_code == 200
    assert b'No coverage totals recorded' in result.data
