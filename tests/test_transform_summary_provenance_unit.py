import json

from mht.utils.io import file_meta, write_json
from mht.utils.stamps import save_stamp


def test_summary_hash_is_recorded_externally(tmp_path):
    summary_path = tmp_path / "transform_summary.json"
    stamp_path = tmp_path / "transform.json"

    summary = {
        "header": {
            "schema_id": "mht.summary.transform",
        },
        "provenance": {
            "outputs": [
                {"path": "exotica_lit_wiki.json"},
                {"path": "exotica_lit_raw_data.json"},
            ]
        },
        "counts": {
            "final_included": 1988,
        },
    }

    # Write the completed summary once.
    assert write_json(summary_path, summary, sort_keys=False)

    # Record its hash in the external stage stamp.
    stamp = {
        "stage_id": "mht.stage.transform",
        "outputs": [file_meta(summary_path)],
    }
    save_stamp(stamp_path, stamp)

    saved_summary = json.loads(
        summary_path.read_text(encoding="utf-8")
    )
    saved_stamp = json.loads(
        stamp_path.read_text(encoding="utf-8")
    )

    summary_metadata = saved_stamp["outputs"][0]

    assert saved_summary == summary
    assert summary_metadata["sha256"] == file_meta(summary_path)["sha256"]
    assert summary_metadata["size_bytes"] == summary_path.stat().st_size

    # The summary should not include its own output metadata.
    assert all(
        output["path"] != summary_path.as_posix()
        for output in saved_summary["provenance"]["outputs"]
    )
