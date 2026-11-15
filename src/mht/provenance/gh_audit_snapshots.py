"""Immutable, source-verified snapshots of Gaming History audit findings.

This module never parses GH data or changes the active audit report. It copies a
verified audit into release-specific revision history and refuses collisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from mht.utils.paths import archives_dir, history_audit_findings_path, summaries_dir

_NAME = re.compile(r"history(\d{3,4})([a-z]?)\.zip", re.IGNORECASE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_audit(audit: dict, release: str, archive: Path) -> dict:
    if not isinstance(audit, dict) or audit.get("schema_id") != "mht.history.audit_findings":
        raise ValueError("Unexpected History audit format")
    if audit.get("release") != release or not isinstance(audit.get("findings"), list):
        raise ValueError("Audit release or findings are invalid")
    if not isinstance(audit.get("detectors"), dict):
        raise ValueError("Audit detector versions are missing")
    match = _NAME.fullmatch(archive.name)
    if not match or f"{int(match.group(1)):04d}" != release:
        raise ValueError(f"Archive does not match release {release}: {archive.name}")
    provenance = audit.get("provenance")
    inputs = provenance.get("inputs") if isinstance(provenance, dict) else None
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
        raise ValueError("Audit has no unambiguous source provenance")
    source = inputs[0]
    if source.get("zip_archive") != archive.name:
        raise ValueError("Audit was generated from a different GH ZIP")
    member = source.get("zip_member")
    if not isinstance(member, str) or Path(member).name.lower() != "history.xml":
        raise ValueError("Audit does not identify a history.xml source member")
    try:
        with ZipFile(archive) as zf:
            if member not in zf.namelist():
                raise ValueError(f"History member missing from ZIP: {member}")
            if zf.getinfo(member).is_dir():
                raise ValueError("History member points to a directory")
    except (OSError, BadZipFile) as exc:
        raise ValueError(f"Cannot inspect GH ZIP: {exc}") from exc
    return source



def revision_snapshot_path(release: str, archive: Path) -> Path | None:
    """Return the required snapshot path for a canonical GH archive.

    Non-canonical fixture names and missing sources have no required snapshot.
    Real revision selection only returns canonical historyNNN[a-z].zip files.
    """
    archive = Path(archive)
    match = _NAME.fullmatch(archive.name)
    if not match or f"{int(match.group(1)):04d}" != release:
        return None
    return summaries_dir(release) / "gh_audit_revisions" / f"{archive.stem.lower()}.json"


def preserve_gh_audit_snapshot(
    release: str,
    archive: Path,
    audit_path: Path,
    snapshot_dir: Path,
) -> tuple[Path, bool]:
    """Preserve an audit once per ZIP revision; return (path, created).

    Existing snapshots are not overwritten, including on later detector changes.
    All validation is done before creating the snapshot destination directory.
    """
    archive, audit_path, snapshot_dir = map(Path, (archive, audit_path, snapshot_dir))
    try:
        audit_bytes = audit_path.read_bytes()
        audit = json.loads(audit_bytes)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Cannot read active GH audit: {exc}") from exc
    source = _validate_audit(audit, release, archive)
    digest = _sha256(archive)
    snapshot = {
        "schema_id": "mht.gh.audit_snapshot",
        "schema_version": "1.0.0",
        "release": release,
        "revision_archive": archive.name,
        "revision_archive_sha256": digest,
        "audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
        "source_member": source["zip_member"],
        "audit": audit,
    }
    target = snapshot_dir / f"{archive.stem.lower()}.json"
    content = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if target.exists():
        if target.read_bytes() == content:
            return target, False
        raise ValueError(f"Revision snapshot already exists with different contents: {target}")
    # Exclusive creation guarantees that a competing writer cannot overwrite a
    # snapshot. A failure cleans up its own partial file.
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            try:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                target.unlink(missing_ok=True)
                raise
    except FileExistsError as exc:
        raise ValueError(f"Revision snapshot appeared during write: {target}") from exc
    return target, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preserve the currently processed GH audit by revision")
    parser.add_argument("--version", required=True, help="Four-digit MHT release, e.g. 0289")
    parser.add_argument("--archive", required=True, help="Archive filename, e.g. history289a.zip")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d{4}", args.version):
        parser.error("--version must be four digits")
    if Path(args.archive).name != args.archive:
        parser.error("--archive must be a filename within the release archives directory")
    try:
        target, created = preserve_gh_audit_snapshot(
            args.version,
            archives_dir(args.version) / args.archive,
            history_audit_findings_path(args.version),
            summaries_dir(args.version) / "gh_audit_revisions",
        )
    except (OSError, ValueError) as exc:
        print(f"[gh-audit-snapshot] Refused: {exc}")
        return 1
    print(f"[gh-audit-snapshot] {'Created' if created else 'Already preserved'}: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
