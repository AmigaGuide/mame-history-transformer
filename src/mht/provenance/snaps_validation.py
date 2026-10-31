"""
Validate downloaded progetto-SNAPS archives before staging.

Validation checks archive integrity, expected filename,
release matching, CatList uniqueness and parseability.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile
import re

from mht.provenance.snaps_sources import SnapsSource
from mht.utils.snaps import parse_catlist


def extract_catlist_metadata(content: str) -> dict:
    """
    Extract version and date information from a CatList header.

    Embedded metadata is authoritative when present.
    Missing metadata remains explicitly unknown.
    """
    metadata = {
        "catlist_version": None,
        "mame_version": None,
        "source_date": None,
    }

    # Limit inspection to the initial header region.
    header = "\n".join(content.splitlines()[:30])

    match = re.search(
        r"CATLIST\.ini\s+(\d+\.\d+)\s*/\s*"
        r"(\d{1,2}-[A-Za-z]{3}-\d{2,4})\s*/\s*"
        r"MAME\s+(\d+\.\d+)",
        header,
        flags=re.IGNORECASE,
    )

    if match:
        metadata["catlist_version"] = match.group(1)
        metadata["source_date"] = match.group(2)
        metadata["mame_version"] = match.group(3)

    return metadata


def validate_snaps_archive(
    archive_path: str | Path,
    source: SnapsSource,
) -> dict:
    """
    Validate a SNAPS ZIP against its resolved source.

    Raises ValueError on validation failure.
    Returns basic archive provenance on success.
    """
    path = Path(archive_path)

    if path.name != source.filename:
        raise ValueError(
            f"Unexpected SNAPS filename: {path.name}"
        )

    try:
        with ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("SNAPS ZIP integrity check failed")

            members = [
                info
                for info in archive.infolist()
                if not info.is_dir()
                and Path(info.filename).name.lower() == "catlist.ini"
            ]

            if len(members) != 1:
                raise ValueError(
                    f"Expected one CatList; found {len(members)}"
                )

            member = members[0]
            content = archive.read(member).decode(
                "utf-8-sig",
                errors="replace",
            )

            classifications = parse_catlist(content)

            if not classifications:
                raise ValueError("SNAPS CatList is empty")

            embedded = extract_catlist_metadata(content)

            declared_mame_version = embedded["mame_version"]

            if declared_mame_version is not None:
                expected_release = (
                    "0" + declared_mame_version.split(".", 1)[1]
                ).zfill(4)

                if expected_release != source.release:
                    raise ValueError(
                        "SNAPS release mismatch: "
                        f"archive expects {source.release}, "
                        f"CatList declares {declared_mame_version}"
                    )

            return {
                "release": source.release,
                "package_type": source.package_type,
                "filename": source.filename,
                "source_url": source.url,
                "catlist_member": member.filename,
                "catlist_crc32": f"{member.CRC:08x}",
                "catlist_size_bytes": member.file_size,
                "classifications": len(classifications),
                "embedded_metadata": embedded,
            }

    except (BadZipFile, OSError, UnicodeError) as exc:
        raise ValueError(
            f"Invalid SNAPS archive: {exc}"
        ) from exc
