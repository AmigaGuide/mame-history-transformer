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
    (data / "incoming" / mame_name).write_bytes(b"exists")
    (data / "incoming" / gh_name).write_bytes(b"exists")

    # Stub network fns so we never hit the net
    monkeypatch.setattr(fetch, "mame_download",
                        lambda url, dest: {"ok": True, "path": str(dest), "size": 1, "sha256": "x", "note": "downloaded"})
    monkeypatch.setattr(fetch, "gh_download",
                        lambda url, dest: {"ok": True, "path": str(dest), "size": 1, "sha256": "y", "note": "downloaded"})

    res = fetch.perform_downloads(plan, ingest=False, overwrite=False)

    assert res["downloads"] == []
    assert {s["name"] for s in res["skipped"]} == {mame_name, gh_name}
