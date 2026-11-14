"""Single authoritative, read-only Gaming History source ZIP selector.

Only canonical historyNNN[revision].zip archives for the requested release
are eligible. No fallback to an unrelated ZIP and no network operations.
"""
from __future__ import annotations

from pathlib import Path
import re

from mht.utils.paths import archives_dir

_HISTORY_NAME = re.compile(r"history(\d{3,4})([a-z]?)\.zip", re.IGNORECASE)


def select_history_archive(version: str, *, directory: Path | None = None) -> Path | None:
    """Return the newest staged GH revision, or None when none is recognised.

    A base archive is revision 0; a..z are revisions 1..26. Refuse
    case-insensitive duplicate revision filenames rather than picking one
    arbitrarily. This function does not inspect ZIP contents; ingestion
    verification remains responsible for validating embedded metadata.
    """
    if not re.fullmatch(r"\d{4}", version):
        raise ValueError("Expected a four-digit MHT release key, e.g. 0289")
    folder = Path(directory) if directory is not None else archives_dir(version)
    if not folder.is_dir():
        return None
    matches: dict[int, Path] = {}
    for path in folder.iterdir():
        if not path.is_file():
            continue
        match = _HISTORY_NAME.fullmatch(path.name)
        if not match or f"{int(match.group(1)):04d}" != version:
            continue
        revision = match.group(2).lower()
        rank = 0 if not revision else ord(revision) - ord("a") + 1
        if rank in matches:
            raise ValueError(
                f"Ambiguous Gaming History revision for {version}: "
                f"{matches[rank].name} and {path.name}"
            )
        matches[rank] = path
    return matches[max(matches)] if matches else None
