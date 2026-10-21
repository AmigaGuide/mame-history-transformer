
from mht.utils.stamps import (
    save_stamp,
    stage_is_fresh,
)


def test_missing_output_invalidates_fresh_stamp(tmp_path):
    stamps = tmp_path / ".stamps"
    source = tmp_path / "input.xml"
    output = tmp_path / "output.json"

    source.write_text("unchanged input", encoding="utf-8")
    output.write_text("{}", encoding="utf-8")

    kwargs = {
        "stamp_filename": "example.json",
        "schema_id": "mht.stage.test",
        "tool": "transformer",
        "inputs": [source],
        "stamps_dir": stamps,
        "outputs": [output],
    }

    # No previous stamp: stage must run.
    fresh, stamp_path, current = stage_is_fresh(**kwargs)
    assert fresh is False

    # Simulate a successful processing stage.
    save_stamp(stamp_path, current)

    # Unchanged input and existing output: skip.
    fresh, _, _ = stage_is_fresh(**kwargs)
    assert fresh is True

    # Delete the output without changing the input.
    output.unlink()

    # The missing output must force a rebuild.
    fresh, _, _ = stage_is_fresh(**kwargs)
    assert fresh is False

    # Simulate regeneration of the missing output.
    output.write_text("{}", encoding="utf-8")

    # The stage should be fresh again.
    fresh, _, _ = stage_is_fresh(**kwargs)
    assert fresh is True


def test_output_checks_remain_optional(tmp_path):
    source = tmp_path / "input.xml"
    source.write_text("unchanged input", encoding="utf-8")

    kwargs = {
        "stamp_filename": "example.json",
        "schema_id": "mht.stage.test",
        "tool": "transformer",
        "inputs": [source],
        "stamps_dir": tmp_path / ".stamps",
    }

    fresh, stamp_path, current = stage_is_fresh(**kwargs)
    assert fresh is False

    save_stamp(stamp_path, current)

    fresh, _, _ = stage_is_fresh(**kwargs)
    assert fresh is True
