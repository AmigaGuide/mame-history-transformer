from mht.utils.stamps import (
    save_stamp,
    stage_is_fresh,
)


def test_snaps_archive_change_invalidates_transform_stamp(tmp_path):
    inputs_dir = tmp_path / "archives"
    inputs_dir.mkdir()

    snaps_zip = inputs_dir / "pS_SupportFiles_287.zip"
    snaps_zip.write_bytes(b"original")

    stamps = tmp_path / "stamps"
    output = tmp_path / "transform_output.json"
    output.write_text("{}", encoding="utf-8")

    def check_freshness():
        return stage_is_fresh(
            "transform.json",
            schema_id="mht.stage.transform",
            tool="transformer",
            inputs=[snaps_zip],
            stamps_dir=stamps,
            outputs=[output],
        )

    fresh, stamp_path, current_stamp = check_freshness()
    assert fresh is False

    save_stamp(stamp_path, current_stamp)

    fresh, _, _ = check_freshness()
    assert fresh is True

    snaps_zip.write_bytes(b"updated archive content")

    fresh, _, _ = check_freshness()
    assert fresh is False
