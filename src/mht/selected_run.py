"""Run one prepared MHT stage without invoking the full pipeline.

This is deliberately separate from main.py: full runs continue to own
archive/encoding detection and the full run manifest. Selected runs reuse
an existing release's encoding cache and write the selected stage's ordinary
outputs and stamp only.
"""
from __future__ import annotations

import json
from pathlib import Path

from mht.utils import paths
from mht.utils.stage_contracts import StageContract, stage_contract
from mht.utils.stamps import stage_is_fresh
from mht.utils.snaps import find_snaps_archive
from mht.provenance.gh_archive_selection import select_history_archive
from mht.utils.gh_encoding_guard import check_gh_encoding_cache

STAGES = ("ini", "mame", "history", "transform")


def _preferred_zip(version: str, token: str) -> Path | None:
    """Mirror the parsers' preferred ZIP then alphabetical fallback."""
    folder = paths.archives_dir(version)
    zips = sorted(folder.glob("*.zip"), key=lambda path: path.name.lower())
    preferred = [p for p in zips if token in p.name.lower()]
    return (preferred or zips or [None])[0]


def _contract(stage: str, version: str) -> StageContract:
    if stage in ("ini", "history"):
        return stage_contract(stage, version, source=select_history_archive(version))
    if stage == "mame":
        return stage_contract(stage, version, source=_preferred_zip(version, "mame"))
    if stage == "transform":
        return stage_contract(
            stage,
            version,
            snaps_archive=find_snaps_archive(paths.archives_dir(version)),
        )
    raise ValueError(f"Unknown stage: {stage}")


def _problems(contract: StageContract) -> list[str]:
    problems = []
    if contract.missing_source:
        problems.append("required source archive is missing")
    for path in contract.inputs:
        if path not in contract.optional_inputs and not path.is_file():
            problems.append(f"required input missing: {path}")
    return problems


def _fresh(contract: StageContract, version: str) -> bool:
    fresh, _, _ = stage_is_fresh(
        contract.stamp_filename,
        schema_id=contract.schema_id,
        tool=contract.tool,
        inputs=contract.inputs,
        stamps_dir=paths.stamps_dir(version),
        outputs=contract.outputs,
    )
    return fresh and not _problems(contract)


def _load_encodings(version: str, stage: str) -> dict[str, str]:
    path = paths.encodings_cache_path(version)
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Cannot read encoding cache {path}: {exc}") from exc
    if not isinstance(root, dict):
        raise ValueError(f"Invalid encoding cache format: {path}")
    encodings = {
        leaf: record.get("encoding") or "utf-8"
        for leaf, record in root.items()
        if isinstance(record, dict)
    }
    if stage == "mame" and "mame.xml" not in encodings:
        raise ValueError(f"Encoding cache does not contain mame.xml: {path}")
    return encodings


def _execute(stage: str, version: str, encodings: dict[str, str]) -> bool:
    """Call existing stage runners; leave their parsing semantics unchanged."""
    if stage == "ini":
        from mht.inputs.history_ini_parser import parse_history_inis
        return bool(parse_history_inis(paths.DATA_DIR, encodings))
    if stage == "mame":
        from mht.inputs.mame_parser import parse_mame_xml
        return bool(parse_mame_xml(paths.mame_xml_path(version), encodings, max_records=0))
    if stage == "history":
        from mht.inputs.history_xml_parser import parse_history_entries
        return bool(parse_history_entries(
            paths.history_xml_path(version), encodings.get("history.xml", "utf-8")
        ))
    if stage == "transform":
        from mht.transform.pipeline import run_transformer
        return bool(run_transformer())
    raise ValueError(f"Unknown stage: {stage}")


def run_selected(stage: str, *, force: bool = False) -> int:
    """Run only *stage* for the active release; return a shell exit code."""
    if stage not in STAGES:
        print(f"[run] Unknown stage: {stage}")
        return 2

    version = paths.active_version()
    try:
        contract = _contract(stage, version)
    except (OSError, ValueError) as exc:
        print(f"[run] Cannot resolve {stage} source: {exc}")
        return 1

    problems = _problems(contract)
    if problems:
        for problem in problems:
            print(f"[run] {stage}: {problem}")
        print("[run] No files or stamps were changed.")
        return 1

    # A transform-only request must never publish from stale upstream data.
    if stage == "transform":
        stale = []
        for upstream in ("ini", "mame", "history"):
            try:
                upstream_contract = _contract(upstream, version)
            except (OSError, ValueError):
                stale.append(upstream)
                continue
            if not _fresh(upstream_contract, version):
                stale.append(upstream)
        if stale:
            print(f"[run] Transform blocked; upstream stage(s) not fresh: {', '.join(stale)}")
            print("[run] Run the required upstream stages or use the full pipeline.")
            return 1

    if not force and _fresh(contract, version):
        print(f"[run] {stage} is already fresh; nothing to rebuild.")
        return 0

    encodings = {}
    if stage != "transform":
        try:
            # Do not run GH stages using a cache from a superseded revision.
            # Preflight happens before --force can remove an existing stamp.
            if stage in ("ini", "history"):
                # The contract already resolved the authoritative GH source.
                # Reuse it, rather than discovering a potentially different
                # archive or bypassing the stage contract in isolated tests.
                source = contract.inputs[0] if not contract.missing_source else None
                if source is None or not source.is_file():
                    raise ValueError("No staged Gaming History archive")
                # Both paths are resolved by the same stage contract.
                check_gh_encoding_cache(
                    version, source, stage, cache_path=contract.inputs[1]
                )
            encodings = _load_encodings(version, stage)
        except ValueError as exc:
            print(f"[run] {exc}")
            print("[run] No stage outputs or stamps were changed.")
            print("[run] Refresh encoding provenance before running this stage.")
            return 1

    # Force is explicit: remove only this stage's stamp after validating inputs.
    # On failure, the missing stamp correctly leaves the stage marked stale.
    if force:
        stamp = paths.stamps_dir(version) / contract.stamp_filename
        try:
            stamp.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[run] Cannot invalidate stage stamp {stamp}: {exc}")
            return 1
        print(f"[run] Force rebuilding {stage} for release {version}.")
    else:
        print(f"[run] Rebuilding stale {stage} for release {version}.")

    try:
        success = _execute(stage, version, encodings)
    except (OSError, ValueError, KeyError) as exc:
        print(f"[run] {stage} failed: {exc}")
        return 1
    if not success:
        print(f"[run] {stage} failed; check the stage log.")
        return 1

    print(f"[run] {stage} completed successfully.")
    if stage != "transform":
        print("[run] Transform was not run. Check 'mht status' for downstream freshness.")
    print("[run] The full-run manifest was not regenerated by this selected run.")
    return 0
