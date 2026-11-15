"""Automatic audit snapshot path and History stage freshness contracts."""
from pathlib import Path

from mht.provenance.gh_audit_snapshots import revision_snapshot_path
from mht.utils import paths
from mht.utils.stage_contracts import stage_contract
from mht.utils import stamps


def test_revision_snapshots_distinguish_base_and_letter_revisions(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'summaries_dir', lambda version=None: tmp_path / str(version) / 'summaries')
    # The snapshot utility imports the function at module scope.
    import mht.provenance.gh_audit_snapshots as audit_snapshots
    monkeypatch.setattr(audit_snapshots, 'summaries_dir', lambda version=None: tmp_path / str(version) / 'summaries')
    assert revision_snapshot_path('0289', Path('history289.zip')).name == 'history289.json'
    assert revision_snapshot_path('0289', Path('history289a.zip')).name == 'history289a.json'
    assert revision_snapshot_path('0289', Path('history289b.zip')).name == 'history289b.json'


def test_revision_snapshot_path_rejects_unrelated_source():
    assert revision_snapshot_path('0289', Path('history290.zip')) is None
    assert revision_snapshot_path('0289', Path('mame0289.zip')) is None
    assert revision_snapshot_path('0289', Path('history.zip')) is None


def test_history_stage_requires_audit_snapshot(tmp_path, monkeypatch):
    import mht.provenance.gh_audit_snapshots as audit_snapshots
    monkeypatch.setattr(audit_snapshots, 'summaries_dir', lambda version=None: tmp_path / 'summaries')
    monkeypatch.setattr(paths, 'summaries_dir', lambda version=None: tmp_path / 'summaries')
    contract = stage_contract('history', '0289', source=tmp_path / 'history289a.zip')
    assert contract.outputs[-1] == tmp_path / 'summaries' / 'gh_audit_revisions' / 'history289a.json'
    assert paths.history_audit_findings_path('0289') in contract.outputs


def test_history_missing_snapshot_is_not_fresh(tmp_path, monkeypatch):
    import mht.provenance.gh_audit_snapshots as audit_snapshots
    monkeypatch.setattr(audit_snapshots, 'summaries_dir', lambda version=None: tmp_path / 'summaries')
    monkeypatch.setattr(paths, 'summaries_dir', lambda version=None: tmp_path / 'summaries')
    monkeypatch.setattr(paths, 'outputs_dir', lambda version=None: tmp_path / 'outputs')
    monkeypatch.setattr(paths, 'encodings_cache_path', lambda version=None: tmp_path / 'encodings.json')
    source = tmp_path / 'history289a.zip'
    source.write_bytes(b'zip-fixture')
    contract = stage_contract('history', '0289', source=source)
    for output in contract.outputs[:-1]:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{}', encoding='utf-8')
    assert not contract.outputs[-1].exists()
    assert any(not p.is_file() for p in contract.outputs)
    assert all(p.is_file() for p in contract.outputs[:-1])
