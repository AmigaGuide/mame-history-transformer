"""Regressions for compact summary pages with downloadable original JSON."""
from __future__ import annotations

import json

import pytest

from mht.preview.app import create_app
from mht.preview.preview_data import PreviewData

SUMMARIES = ('mame', 'history', 'ini', 'transform')


@pytest.fixture
def client():
    data = PreviewData(
        wiki_doc={}, wiki_games={}, trivia_by_machine={}, mame_machines={},
        mame_summary={'header': {'schema_id': 'mht.mame.summary'}, 'sentinel': 'MAME_SECRET_MARKER'},
        history_summary={'header': {'schema_id': 'mht.history.summary'}, 'sentinel': 'HISTORY_SECRET_MARKER'},
        ini_summary={'header': {'schema_id': 'mht.ini.summary'}, 'sentinel': 'INI_SECRET_MARKER'},
        transform_summary={'header': {'schema_id': 'mht.transform.summary'}, 'sentinel': 'TRANSFORM_SECRET_MARKER'},
        machine_order=[],
    )
    app = create_app(data, version='0289')
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.mark.parametrize('stage', SUMMARIES)
def test_summary_page_links_to_json_without_embedding_it(client, stage):
    response = client.get(f'/summary/{stage}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'/summary/{stage}/source.json' in html
    assert 'downloadable JSON' in html
    assert f'{stage.upper()}_SECRET_MARKER' not in html
    assert '<h2>Raw JSON</h2>' not in html


@pytest.mark.parametrize('stage', SUMMARIES)
def test_download_is_exact_loaded_summary_and_attachment(client, stage):
    response = client.get(f'/summary/{stage}/source.json')
    assert response.status_code == 200
    assert response.mimetype == 'application/json'
    assert response.headers['Content-Disposition'] == (
        f'attachment; filename="mht_{stage}_summary.json"'
    )
    assert json.loads(response.data)['sentinel'] == f'{stage.upper()}_SECRET_MARKER'


def test_unknown_stage_cannot_download_a_file(client):
    assert client.get('/summary/unknown/source.json').status_code == 404
    assert client.get('/summary/../../etc/passwd/source.json').status_code == 404
