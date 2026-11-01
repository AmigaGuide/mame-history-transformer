from zipfile import ZipFile


def test_perform_downloads_skips_existing(monkeypatch, tmp_path):
    data = tmp_path / "data"; (data / "incoming").mkdir(parents=True)

    import mht.provenance.fetch as fetch
    # point the incoming dir to tmp
    monkeypatch.setattr(fetch, "INCOMING_DIR", data / "incoming", raising=False)

    # Build a plan identical to what your code expects
    plan = fetch.FetchPlan(
        current_core="0.281",
        next_core="0.282",      # important: exactly the format your code uses
        next_key="0282",
        mame={"url": "https://example/mame0282lx.zip"},
        gh={"url": "https://example/history282.zip", "suffix": ""},
        action="both",
    )

    # Derive the filenames exactly as perform_downloads() will
    mame_name = f"mame{plan.next_key}lx.zip"
    gh_core   = fetch._core_no_dot(plan.next_core)  # use the same helper
    gh_name   = f"history{gh_core}.zip"

    # Seed existing files with those exact names
    with ZipFile(data / "incoming" / mame_name, "w") as archive:
        archive.writestr(
            "mame0282.xml",
            '<mame build="0.282 (mame0282)" mameconfig="10"/>',
        )

    with ZipFile(data / "incoming" / gh_name, "w") as archive:
        archive.writestr(
            "history/history.xml",
            '<history version="2.82" date="2026-01-01"/>',
        )

    # Stub network functions so we never hit the network.
    # Simulate the wrappers recognising verified existing archives.
    monkeypatch.setattr(
        fetch,
        "mame_download",
        lambda url, dest, *, overwrite=False: {
            "ok": True,
            "path": str(dest),
            "reason": "exists",
            "note": "existing verified archive",
        },
    )

    monkeypatch.setattr(
        fetch,
        "gh_download",
        lambda url, dest, *, overwrite=False: {
            "ok": True,
            "path": str(dest),
            "reason": "exists",
            "note": "existing verified archive",
        },
    )

    res = fetch.perform_downloads(plan, ingest=False, overwrite=False)

    assert res["downloads"] == []
    assert {s["name"] for s in res["skipped"]} == {mame_name, gh_name}
