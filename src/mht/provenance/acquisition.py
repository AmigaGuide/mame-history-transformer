"""
Shared acquisition provenance for upstream ZIP archives.

Initially provides a read-only inventory of archive files.
It does not write manifests or modify source archives.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from mht.provenance.peek import derive_mame_version_hint_from_filename
from mht.utils.io import sha256_file
from mht.utils.paths import archives_dir
from mht.provenance.peek import peek_path
from mht.provenance.snaps_sources import SnapsSource
from mht.provenance.snaps_validation import validate_snaps_archive
from mht.utils.io import write_json


def identify_archive_source(filename: str) -> str:
    """
    Identify a recognised upstream archive by filename.

    Unknown ZIPs remain unknown rather than being assigned
    to a provider through guesswork.
    """
    name = Path(filename).name.lower()

    if re.fullmatch(r"ps_(?:catver|supportfiles)_\d{3}\.zip", name):
        return "snaps"

    if re.fullmatch(r"mame\d{4}lx\.zip", name):
        return "mame"

    if re.fullmatch(r"history\d{3,4}[a-z]?\.zip", name):
        return "gaming_history"

    return "unknown"



def release_from_embedded_version(
    source_type: str,
    version: str | None,
) -> str | None:
    """
    Convert a provider's embedded version into an MHT release key.

    Preserve the original source version separately.
    Return None when the version is missing or unrecognised.
    """
    if not version:
        return None

    if source_type in ("mame", "snaps"):
        match = re.fullmatch(
            r"0\.(\d{3})(?:\s+\(mame\d{4}\))?",
            version.strip(),
            flags=re.IGNORECASE,
        )
        if match:
            return f"0{match.group(1)}"

    elif source_type == "gaming_history":
        match = re.fullmatch(
            r"2\.(\d{2,3})[a-z]?",
            version.strip(),
            flags=re.IGNORECASE,
        )
        if match:
            return f"{200 + int(match.group(1)):04d}"

    return None


def compare_embedded_release(
    source_type: str,
    version: str | None,
    expected_release: str,
) -> dict:
    """
    Compare an embedded source version with the expected release.

    A missing or unrecognised version is not automatically
    treated as a mismatch.
    """
    embedded_release = release_from_embedded_version(
        source_type,
        version,
    )

    if embedded_release is None:
        status = "unverified"
    elif embedded_release == expected_release:
        status = "match"
    else:
        status = "mismatch"

    return {
        "original_version": version,
        "embedded_release": embedded_release,
        "expected_release": expected_release,
        "status": status,
    }


def inspect_archive_metadata(
    archive_path: str | Path,
    expected_release: str,
) -> dict[str, Any]:
    """
    Read embedded release evidence from a recognised archive.

    This checks metadata consistency but does not perform
    a full ZIP-member integrity test.
    """
    path = Path(archive_path)
    provider = identify_archive_source(path.name)

    result: dict[str, Any] = {
        "filename": path.name,
        "source_type": provider,
        "expected_release": expected_release,
        "embedded_version": None,
        "embedded_date": None,
        "member": None,
        "comparison": None,
        "error": None,
    }

    if provider == "unknown":
        result["error"] = "Unrecognised archive provider"
        return result

    try:
        if provider == "snaps":
            package_type = (
                "catver"
                if path.name.lower().startswith("ps_catver_")
                else "supportfiles"
            )

            source = SnapsSource(
                release=expected_release,
                package_type=package_type,
                filename=path.name,
                url="",
            )

            validated = validate_snaps_archive(path, source)
            embedded = validated["embedded_metadata"]

            result["embedded_version"] = embedded["mame_version"]
            result["embedded_date"] = embedded["source_date"]
            result["member"] = validated["catlist_member"]

        else:
            metadata = peek_path(path)

            if metadata.get("error"):
                raise ValueError(str(metadata["error"]))

            if provider == "mame":
                candidate = metadata.get("mame_xml_candidate")
                probe = metadata.get("mame_xml_probe") or {}

                result["embedded_version"] = probe.get("mame_build")

            else:
                candidate = metadata.get("history_xml_candidate")
                probe = metadata.get("history_xml_probe") or {}

                result["embedded_version"] = probe.get(
                    "history_version"
                )
                result["embedded_date"] = probe.get(
                    "history_date"
                )

            if probe.get("error"):
                raise ValueError(str(probe["error"]))

            if candidate:
                result["member"] = candidate["name"]

            if not candidate:
                raise ValueError("Expected XML member not found")

        result["comparison"] = compare_embedded_release(
            provider,
            result["embedded_version"],
            expected_release,
        )

    except (OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def inventory_release_archives(
    release: str,
    *,
    archive_directory: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Inventory ZIP archives belonging to a MAME release.

    No files are changed and no acquisition details are inferred
    from modification timestamps or filename conventions.
    """
    directory = (
        Path(archive_directory)
        if archive_directory is not None
        else archives_dir(release)
    )

    if not directory.exists():
        return []

    records: list[dict[str, Any]] = []

    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".zip":
            continue

        identified_release = derive_mame_version_hint_from_filename(
            path.name
        )

        records.append({
            "filename": path.name,
            "source_type": identify_archive_source(path.name),
            "release": release,
            "filename_release_hint": identified_release,
            "release_matches_filename": (
                identified_release == release
                if identified_release is not None
                else None
            ),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "source_url": None,
            "acquired_at": None,
        })

    return records


def verify_archive_integrity(
    archive_path: str | Path,
) -> dict[str, Any]:
    """
    Verify every member of a ZIP archive.

    Reads compressed members and checks their CRC-32 values.
    Does not extract files or modify the archive.
    """
    path = Path(archive_path)

    result: dict[str, Any] = {
        "status": "error",
        "members_checked": 0,
        "bad_member": None,
        "error": None,
    }

    try:
        with ZipFile(path) as archive:
            members = [
                info for info in archive.infolist()
                if not info.is_dir()
            ]

            bad_member = archive.testzip()

            if bad_member is not None:
                result["status"] = "failed"
                result["bad_member"] = bad_member
            else:
                result["status"] = "passed"
                result["members_checked"] = len(members)

    except (BadZipFile, OSError, RuntimeError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def audit_release_archives(
    release: str,
    *,
    archive_directory: Path | None = None,
    check_integrity: bool = True,
) -> list[dict[str, Any]]:
    """
    Combine file inventory, embedded metadata and ZIP integrity.

    Read-only. No manifests are written and no files are moved.
    """
    directory = (
        Path(archive_directory)
        if archive_directory is not None
        else archives_dir(release)
    )

    records = inventory_release_archives(
        release,
        archive_directory=directory,
    )

    for record in records:
        path = directory / record["filename"]

        inspection = inspect_archive_metadata(path, release)

        record["embedded_metadata"] = inspection
        record["release_verification"] = (
            inspection["comparison"]["status"]
            if inspection.get("comparison")
            else "unverified"
        )

        if check_integrity:
            record["integrity_verification"] = (
                verify_archive_integrity(path)
            )
        else:
            record["integrity_verification"] = {
                "status": "not_checked",
                "members_checked": 0,
                "bad_member": None,
                "error": None,
            }

        integrity = record["integrity_verification"]["status"]

        if (
            record["release_matches_filename"] is False
            or record["release_verification"] == "mismatch"
        ):
            status = "mismatch"
        elif inspection["error"] or integrity in ("failed", "error"):
            status = "error"
        elif (
            record["release_matches_filename"] is True
            and record["release_verification"] == "match"
            and integrity == "passed"
        ):
            status = "verified"
        else:
            status = "unverified"

        record["verification_status"] = status

    return records


def build_acquisition_manifest(
    release: str,
    records: list[dict[str, Any]],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build a per-release acquisition manifest.

    Preserve recorded acquisition details only when both
    archive filename and SHA-256 match a previous record.

    This function does not read or write any files.
    """
    previous_archives = {}

    if previous is not None:
        if previous.get("release") != release:
            raise ValueError(
                "Existing acquisition manifest belongs "
                "to a different release"
            )

        for item in previous.get("archives", []):
            previous_archives[item["filename"]] = item

    archives = []

    for record in records:
        item = dict(record)

        previous_item = previous_archives.get(
            item["filename"]
        )

        if (
            previous_item is not None
            and previous_item.get("sha256") == item["sha256"]
        ):
            item["source_url"] = previous_item.get(
                "source_url"
            )
            item["acquired_at"] = previous_item.get(
                "acquired_at"
            )

        archives.append(item)

    return {
        "schema_id": "mht.acquisition.manifest",
        "schema_version": "1.0.0",
        "release": release,
        "archives": archives,
    }


def save_acquisition_manifest(
    release: str,
    *,
    archive_directory: Path | None = None,
    manifest_path: Path | None = None,
    acquisition_event: dict[str, Any] | None = None,
) -> Path:
    """
    Audit a release and atomically save its acquisition manifest.

    Existing acquisition details are preserved only when
    archive filenames and SHA-256 values remain unchanged.

    Refuse to replace the manifest if any archive fails
    complete verification.
    """
    directory = (
        Path(archive_directory)
        if archive_directory is not None
        else archives_dir(release)
    )

    destination = (
        Path(manifest_path)
        if manifest_path is not None
        else directory.parent / "acquisition_manifest.json"
    )

    records = audit_release_archives(
        release,
        archive_directory=directory,
        check_integrity=True,
    )

    if not records:
        raise ValueError(
            f"No archives found for release {release}"
        )

    problems = [
        record["filename"]
        for record in records
        if record["verification_status"] != "verified"
    ]

    if problems:
        raise ValueError(
            "Acquisition manifest not written: "
            "archive verification incomplete or failed: "
            + ", ".join(problems)
        )

    previous = None

    if destination.exists():
        with destination.open(
            "r",
            encoding="utf-8",
        ) as file:
            previous = json.load(file)

        if not isinstance(previous, dict):
            raise ValueError(
                "Existing acquisition manifest is not a JSON object"
            )

    manifest = build_acquisition_manifest(
        release,
        records,
        previous=previous,
    )

    if acquisition_event is not None:
        manifest = apply_acquisition_event(
            manifest,
            acquisition_event,
        )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_json(
        destination,
        manifest,
        sort_keys=False,
    )

    return destination


def build_acquisition_event(
    archive_path: str | Path,
    source_url: str,
    release: str,
    *,
    acquired_at: str | None = None,
) -> dict[str, Any]:
    """
    Describe a successful upstream archive acquisition.

    This function does not validate the ZIP, write a
    manifest or modify the archive.

    Callers must first establish that the download
    succeeded and the archive is acceptable.
    """
    path = Path(archive_path)
    provider = identify_archive_source(path.name)

    if provider == "unknown":
        raise ValueError(
            f"Unrecognised acquisition source: {path.name}"
        )

    parsed_url = urlparse(source_url)

    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
    ):
        raise ValueError(
            "Acquisition source must be an HTTPS URL"
        )

    filename_release = (
        derive_mame_version_hint_from_filename(path.name)
    )

    if filename_release != release:
        raise ValueError(
            f"Archive {path.name} does not match "
            f"release {release}"
        )

    if not path.is_file():
        raise FileNotFoundError(path)

    timestamp = acquired_at

    if timestamp is None:
        timestamp = (
            datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    return {
        "event_type": "download",
        "source_type": provider,
        "filename": path.name,
        "release": release,
        "source_url": source_url,
        "acquired_at": timestamp,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def apply_acquisition_event(
    manifest: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    """
    Attach a successful download event to its exact archive.

    The archive must already appear in the manifest and
    must have passed complete verification.

    Returns a new manifest without modifying the original.
    """
    import copy

    if event.get("event_type") != "download":
        raise ValueError("Unsupported acquisition event")

    if event.get("release") != manifest.get("release"):
        raise ValueError("Acquisition event release mismatch")

    updated = copy.deepcopy(manifest)

    matches = [
        record
        for record in updated.get("archives", [])
        if record.get("filename") == event.get("filename")
    ]

    if len(matches) != 1:
        raise ValueError(
            "Acquisition event must identify exactly one archive"
        )

    record = matches[0]

    if record.get("sha256") != event.get("sha256"):
        raise ValueError("Acquisition event SHA-256 mismatch")

    if record.get("source_type") != event.get("source_type"):
        raise ValueError("Acquisition event provider mismatch")

    if record.get("verification_status") != "verified":
        raise ValueError(
            "Cannot attach acquisition event to unverified archive"
        )

    if not event.get("source_url") or not event.get("acquired_at"):
        raise ValueError("Incomplete acquisition event")

    record["source_url"] = event["source_url"]
    record["acquired_at"] = event["acquired_at"]

    return updated




def pending_acquisition_path(
    archive_path: str | Path,
) -> Path:
    """
    Return the pending acquisition event path for a ZIP.
    """
    path = Path(archive_path)
    return path.with_name(
        path.name + ".acquisition.json"
    )


def save_pending_acquisition_event(
    archive_path: str | Path,
    event: dict[str, Any],
) -> Path:
    """
    Persist a pending download event beside its archive.

    The event must identify the exact file currently
    present, including its SHA-256 fingerprint.
    """
    path = Path(archive_path)

    if not path.is_file():
        raise FileNotFoundError(path)

    if event.get("event_type") != "download":
        raise ValueError("Unsupported acquisition event")

    if event.get("filename") != path.name:
        raise ValueError("Acquisition filename mismatch")

    if event.get("source_type") != identify_archive_source(path.name):
        raise ValueError("Acquisition provider mismatch")

    if event.get("sha256") != sha256_file(path):
        raise ValueError("Acquisition SHA-256 mismatch")

    if (
        event.get("release")
        != derive_mame_version_hint_from_filename(path.name)
    ):
        raise ValueError("Acquisition release mismatch")

    destination = pending_acquisition_path(path)

    write_json(
        destination,
        event,
        sort_keys=False,
    )

    return destination


def load_pending_acquisition_event(
    archive_path: str | Path,
) -> dict[str, Any] | None:
    """
    Read and verify a pending event against its archive.

    Return None when no pending event exists.
    Reject stale or inconsistent event information.
    """
    path = Path(archive_path)
    destination = pending_acquisition_path(path)

    if not destination.exists():
        return None

    with destination.open("r", encoding="utf-8") as file:
        event = json.load(file)

    if not isinstance(event, dict):
        raise ValueError(
            "Pending acquisition event is not a JSON object"
        )

    if event.get("event_type") != "download":
        raise ValueError("Unsupported acquisition event")

    if event.get("filename") != path.name:
        raise ValueError("Pending acquisition filename mismatch")

    if event.get("source_type") != identify_archive_source(path.name):
        raise ValueError("Pending acquisition provider mismatch")

    if (
        event.get("release")
        != derive_mame_version_hint_from_filename(path.name)
    ):
        raise ValueError("Pending acquisition release mismatch")

    if not path.is_file():
        raise FileNotFoundError(path)

    if event.get("sha256") != sha256_file(path):
        raise ValueError("Pending acquisition SHA-256 mismatch")

    return event


def transfer_pending_acquisition_event(
    original_archive: str | Path,
    staged_archive: str | Path,
) -> Path | None:
    """
    Transfer a pending acquisition event after its ZIP was staged.

    The staged ZIP must match the event's filename and SHA-256.
    If no pending event exists, this was potentially a manual
    import and no acquisition event is fabricated.

    Does not write the release acquisition manifest.
    """
    original = Path(original_archive)
    staged = Path(staged_archive)

    source_event_path = pending_acquisition_path(original)
    destination_event_path = pending_acquisition_path(staged)

    if not source_event_path.exists():
        return None

    if not staged.is_file():
        raise FileNotFoundError(staged)

    if original.name != staged.name:
        raise ValueError("Staged acquisition filename mismatch")

    with source_event_path.open("r", encoding="utf-8") as file:
        event = json.load(file)

    if not isinstance(event, dict):
        raise ValueError("Pending acquisition event is not a JSON object")

    if event.get("event_type") != "download":
        raise ValueError("Unsupported acquisition event")

    if event.get("filename") != staged.name:
        raise ValueError("Pending acquisition filename mismatch")

    if event.get("source_type") != identify_archive_source(staged.name):
        raise ValueError("Pending acquisition provider mismatch")

    if (
        event.get("release")
        != derive_mame_version_hint_from_filename(staged.name)
    ):
        raise ValueError("Pending acquisition release mismatch")

    if event.get("sha256") != sha256_file(staged):
        raise ValueError("Pending acquisition SHA-256 mismatch")

    if destination_event_path.exists():
        raise ValueError(
            "Destination already contains a pending acquisition event"
        )

    source_event_path.replace(destination_event_path)

    return destination_event_path


def finalise_staged_acquisition(
    original_archive: str | Path,
    staged_archive: str | Path,
    release: str,
    *,
    manifest_path: Path | None = None,
) -> Path | None:
    """
    Finish a pending acquisition after its ZIP has been staged.

    Handles a pending event left beside the original incoming
    path or already transferred beside the staged archive.

    Returns the manifest path when an event was committed,
    or None when no pending acquisition event exists.
    """
    original = Path(original_archive)
    staged = Path(staged_archive)

    if not staged.is_file():
        raise FileNotFoundError(staged)

    if original.name != staged.name:
        raise ValueError("Staged acquisition filename mismatch")

    if derive_mame_version_hint_from_filename(staged.name) != release:
        raise ValueError("Staged acquisition release mismatch")

    incoming_pending = pending_acquisition_path(original)
    staged_pending = pending_acquisition_path(staged)

    # When recovering an already-staged ZIP, the original and
    # destination paths may be identical. This is not a conflict.
    same_pending_path = (
        incoming_pending.resolve() == staged_pending.resolve()
    )

    if not same_pending_path:
        if incoming_pending.exists() and staged_pending.exists():
            raise ValueError(
                "Pending acquisition events exist in both locations"
            )

        if incoming_pending.exists():
            transfer_pending_acquisition_event(
                original,
                staged,
            )

    event = load_pending_acquisition_event(staged)

    if event is None:
        return None

    if event["release"] != release:
        raise ValueError("Pending acquisition release mismatch")

    destination = save_acquisition_manifest(
        release,
        archive_directory=staged.parent,
        manifest_path=manifest_path,
        acquisition_event=event,
    )

    # Only discard the pending event after the verified
    # acquisition manifest has been successfully persisted.
    staged_pending.unlink()

    return destination


def recover_staged_acquisitions(
    release: str,
    *,
    archive_directory: Path | None = None,
    manifest_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Recover pending acquisition events already beside staged ZIPs.

    Never moves or replaces an archive. Reports failures without
    deleting pending evidence, so recovery can be attempted again.
    """
    directory = (
        Path(archive_directory)
        if archive_directory is not None
        else archives_dir(release)
    )

    if not directory.is_dir():
        return []

    results: list[dict[str, Any]] = []

    for pending in sorted(directory.glob("*.zip.acquisition.json")):
        filename = pending.name.removesuffix(".acquisition.json")
        staged = directory / filename

        try:
            destination = finalise_staged_acquisition(
                staged,
                staged,
                release,
                manifest_path=manifest_path,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            results.append({
                "filename": filename,
                "release": release,
                "action": "error",
                "reason": "acquisition_recovery_failed",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        results.append({
            "filename": filename,
            "release": release,
            "action": "recovered",
            "acquisition_manifest": destination.as_posix(),
        })

    return results


def recover_stranded_acquisitions(
    release: str,
    *,
    incoming_directory: Path,
    archive_directory: Path | None = None,
    manifest_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Recover pending events left in incoming after their ZIP moved.

    Only considers exact filename matches for the requested
    release, and never moves or overwrites an archive.
    """
    incoming = Path(incoming_directory)
    directory = (
        Path(archive_directory)
        if archive_directory is not None
        else archives_dir(release)
    )

    if not incoming.is_dir():
        return []

    results: list[dict[str, Any]] = []
    suffix = ".zip.acquisition.json"

    for pending in sorted(incoming.glob(f"*{suffix}")):
        filename = pending.name.removesuffix(".acquisition.json")

        if derive_mame_version_hint_from_filename(filename) != release:
            continue

        original = incoming / filename
        staged = directory / filename

        # An incoming ZIP means ingestion may not have started.
        # Do not treat that as an interrupted transfer.
        if original.exists():
            continue

        # The incoming ZIP has gone, but no matching staged ZIP
        # exists. Preserve the JSON and report it for investigation.
        if not staged.is_file():
            results.append({
                "filename": filename,
                "release": release,
                "action": "error",
                "reason": "orphaned_pending_acquisition",
                "error": (
                    "Pending acquisition record has no matching "
                    "ZIP in incoming or release archives"
                ),
            })
            continue

        try:
            destination = finalise_staged_acquisition(
                original,
                staged,
                release,
                manifest_path=manifest_path,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            results.append({
                "filename": filename,
                "release": release,
                "action": "error",
                "reason": "acquisition_recovery_failed",
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        results.append({
            "filename": filename,
            "release": release,
            "action": "recovered",
            "acquisition_manifest": destination.as_posix(),
        })

    return results
