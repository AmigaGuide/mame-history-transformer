import pytest

import mht.provenance.fetch as fetch
import mht.provenance.archives as archives


def make_plan():
    return fetch.FetchPlan(
        current_core="288",
        next_core="289",
        next_key="0289",
        mame={"url": "https://example.com/mame0289lx.zip"},
        gh={
            "url": "https://example.com/history289.zip",
            "suffix": "",
        },
        action="both",
    )


@pytest.fixture
def incoming_directory(monkeypatch, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    monkeypatch.setattr(fetch, "INCOMING_DIR", incoming)

    return incoming


def test_failed_download_blocks_ingestion(
    monkeypatch,
    incoming_directory,
):
    monkeypatch.setattr(
        fetch,
        "mame_download",
        lambda url, dest, *, overwrite=False: {
            "ok": False,
            "reason": "invalid_existing_archive",
        },
    )

    monkeypatch.setattr(
        fetch,
        "gh_download",
        lambda url, dest, *, overwrite=False: {
            "ok": True,
            "note": "downloaded",
        },
    )

    def unexpected_ingestion(**kwargs):
        raise AssertionError("Ingestion must be blocked")

    monkeypatch.setattr(
        archives,
        "import_incoming_archives",
        unexpected_ingestion,
    )

    result = fetch.perform_downloads(
        make_plan(),
        ingest=True,
    )

    assert result["ingest"] == "blocked"
    assert "validations failed" in result["ingest_reason"]


def test_successful_downloads_allow_ingestion(
    monkeypatch,
    incoming_directory,
):
    monkeypatch.setattr(
        fetch,
        "mame_download",
        lambda url, dest, *, overwrite=False: {
            "ok": True,
            "note": "downloaded",
        },
    )

    monkeypatch.setattr(
        fetch,
        "gh_download",
        lambda url, dest, *, overwrite=False: {
            "ok": True,
            "note": "downloaded",
        },
    )

    calls = []

    def fake_ingestion(**kwargs):
        calls.append(kwargs)
        return [{
            "action": "moved",
            "name": "mame0289lx.zip",
        }]

    monkeypatch.setattr(
        archives,
        "import_incoming_archives",
        fake_ingestion,
    )

    result = fetch.perform_downloads(
        make_plan(),
        ingest=True,
    )

    assert result["ingest"] == "done"
    assert len(calls) == 1


def test_ingestion_rejection_is_not_reported_as_success(
    monkeypatch,
    incoming_directory,
):
    monkeypatch.setattr(
        fetch,
        "mame_download",
        lambda url, dest, *, overwrite=False: {
            "ok": True,
        },
    )

    monkeypatch.setattr(
        fetch,
        "gh_download",
        lambda url, dest, *, overwrite=False: {
            "ok": True,
        },
    )

    monkeypatch.setattr(
        archives,
        "import_incoming_archives",
        lambda **kwargs: [{
            "action": "rejected",
            "reason": "invalid_archive",
        }],
    )

    result = fetch.perform_downloads(
        make_plan(),
        ingest=True,
    )

    assert result["ingest"] == "error"
    assert result["ingest_results"][0]["action"] == "rejected"
