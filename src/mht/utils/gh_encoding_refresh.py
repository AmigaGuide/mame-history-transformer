"""Refresh GH encoding provenance using the full pipeline's ZIP-aware detector.

The central encodings.json is the only persisted cache. A proposed refresh is
validated before atomic replacement; unrelated MAME metadata must not change.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from mht.utils.encoding_utils import (
    detect_encodings_from_archives,
    save_encodings_cache,
)
from mht.utils.gh_encoding_guard import check_gh_encoding_cache

CANONICAL_LEAVES = {
    "mame_xml": "mame.xml",
    "history_xml": "history.xml",
    "ini_game": "[GAMING HISTORY] Game Or No Game.ini",
    "ini_category": "[GAMING HISTORY] Machine Category.ini",
    "ini_type": "[GAMING HISTORY] Machine Type.ini",
}


def ensure_gh_encodings(
    version: str,
    history_archive: Path,
    stage: str,
    *,
    cache_path: Path,
    mame_archive: Path | None = None,
) -> bool:
    """Return True if the cache needed refreshing, False if already current.

    All validation is completed before replacing the cache. Missing, malformed
    caches are rejected rather than silently repopulated by a selected run.
    """
    if stage not in ("ini", "history"):
        raise ValueError(f"Unsupported GH stage: {stage}")
    path = Path(cache_path)
    history_archive = Path(history_archive)
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Cannot read encoding cache {path}: {exc}") from exc
    if not isinstance(prior, dict):
        raise ValueError(f"Invalid encoding cache {path}: expected object")

    try:
        check_gh_encoding_cache(version, history_archive, stage, cache_path=path)
    except ValueError:
        # Revalidate with the shared detector. We must have an actual staged
        # MAME ZIP, even though its already-cached member should be reused.
        if mame_archive is None or not Path(mame_archive).is_file() or Path(mame_archive).suffix.lower() != ".zip":
            raise ValueError("Cannot refresh GH encodings without a staged MAME ZIP") from None
    else:
        return False

    if not isinstance(prior.get("mame.xml"), dict):
        raise ValueError("Cannot refresh GH encodings: existing MAME provenance is missing")

    try:
        proposed, _ = detect_encodings_from_archives(
            mame_archive=Path(mame_archive),
            history_archive=history_archive,
            canonical_leaves=CANONICAL_LEAVES,
            prior=prior,
        )
    except Exception as exc:
        raise ValueError(f"GH encoding detection failed: {exc}") from exc
    if not isinstance(proposed, dict):
        raise ValueError("GH encoding detector returned invalid cache data")
    if proposed.get("mame.xml") != prior["mame.xml"]:
        raise ValueError("Refusing GH refresh: MAME encoding provenance would change")

    # Validate the whole GH selection (XML AND INIs), not just the requested
    # stage, before writing the shared cache to disk.
    with TemporaryDirectory(prefix="mht-gh-cache-") as temp:
        candidate = Path(temp) / "encodings.json"
        candidate.write_text(json.dumps(proposed, ensure_ascii=False), encoding="utf-8")
        for selected_stage in ("history", "ini"):
            try:
                check_gh_encoding_cache(version, history_archive, selected_stage, cache_path=candidate)
            except ValueError as exc:
                raise ValueError(f"Refreshed GH encoding provenance invalid: {exc}") from exc

    try:
        save_encodings_cache(path, proposed)
    except OSError as exc:
        raise ValueError(f"Cannot persist refreshed encoding cache {path}: {exc}") from exc
    return True
