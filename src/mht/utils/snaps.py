"""
Parse progetto-SNAPS CatList classifications.

CatList groups MAME machines by gameplay classification.
Arcade machines use headings prefixed with "Arcade: ".

This module does not decide whether a machine is eligible
for MHT output. It only extracts source classifications.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile


def find_snaps_archive(archive_dir: str | Path) -> Path | None:
    """
    Find the SNAPS ZIP in a release's archives directory.

    Returns None when no matching archive is available.
    """
    directory = Path(archive_dir)

    if not directory.is_dir():
        return None

    matches = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".zip"
            and path.name.lower().startswith("ps_")
        ),
        key=lambda path: path.name.lower(),
    )

    if len(matches) > 1:
        raise ValueError(
            f"Multiple SNAPS archives found in {directory}"
        )

    return matches[0] if matches else None


MATURE_SUFFIX = " * Mature *"


def parse_catlist(content: str) -> dict[str, dict[str, str]]:
    """
    Parse CatList INI text into machine classifications.

    Returns:
        {
            "machine": {
                "group": "Arcade" | "Non-Arcade",
                "category": "Shooter",
                "subcategory": "Flying Vertical",
            }
        }

    Maturity markers are ignored for classification purposes.
    """
    result = {}
    section = None

    for raw in content.splitlines():
        line = raw.strip()

        if not line or line.startswith((";", "#")):
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue

        if section in (
            None,
            "FOLDER_SETTINGS",
            "ROOT_FOLDER",
        ):
            continue

        if "=" in line:
            continue

        if section.startswith("Arcade: "):
            group = "Arcade"
            classification = section[len("Arcade: "):]
        else:
            group = "Non-Arcade"
            classification = section

        if classification.endswith(MATURE_SUFFIX):
            classification = classification[:-len(MATURE_SUFFIX)]

        category, separator, subcategory = (
            classification.partition(" / ")
        )

        record = {
            "group": group,
            "category": category.strip(),
            "subcategory": (
                subcategory.strip() if separator else ""
            ),
        }

        if line in result and result[line] != record:
            raise ValueError(
                f"Conflicting SNAPS classification for {line}: "
                f"{result[line]} versus {record}"
            )

        result[line] = record

    return result


def load_catlist(
    archive_path: str | Path,
    member: str,
) -> dict[str, dict[str, str]]:
    """
    Read CatList directly from a progetto-SNAPS ZIP archive.
    """
    with ZipFile(archive_path) as archive:
        content = archive.read(member).decode(
            "utf-8-sig",
            errors="replace",
        )

    return parse_catlist(content)


def load_release_snaps(
    archive_dir: str | Path,
) -> dict[str, dict[str, str]] | None:
    """
    Load SNAPS CatList classifications from a release archive.

    Returns None when no SNAPS archive is available.
    Raises ValueError if the archive has no unique CatList.
    """
    archive_path = find_snaps_archive(archive_dir)

    if archive_path is None:
        return None

    with ZipFile(archive_path) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.lower().endswith("/catlist.ini")
            or name.lower() == "catlist.ini"
        ]

    if len(members) != 1:
        raise ValueError(
            f"Expected one CatList in {archive_path.name}; "
            f"found {len(members)}"
        )

    return load_catlist(archive_path, members[0])


# Categories describing machines outside the normal arcade
# video-game scope. These are not PORTS exclusion rules.
EXCLUDED_ARCADE_CATEGORIES = frozenset({
    "Casino",
    "Electromechanical",
    "Gambling",
    "Medal Game",
    "Redemption Game",
    "Slot Machine",
})

# Descriptive GH machine types identifying specialised
# equipment rather than ordinary arcade video games.
# Unknown types are allowed, not automatically rejected.
EXCLUDED_MACHINE_TYPE_TERMS = (
    "fruit machine",
    "slot machine",
    "pinball",
    "medal game",
    "redemption game",
    "kiddie ride",
    "pachinko",
    "bowler",
    "dart game",
    "air hockey",
    "strength tester",
    "wall game",
    "bat game",
    "bingo",
    "igt player",
    "igt super player",
    "coin-op misc.",
    "gun game (mechanical)",
    "barcrest mpu",
)


def _mame_flag(value: object) -> bool:
    """Interpret boolean flags supplied by MAME XML."""
    return (
        value is True
        or value == 1
        or isinstance(value, str)
        and value.strip().casefold() in ("yes", "true", "1")
    )


def snaps_eligibility_reason(
    machine: str,
    mame: dict,
    gh_classifications: dict,
    snaps_classifications: dict,
) -> str:
    """
    Explain normal arcade eligibility for one MAME machine.

    Returns 'eligible' or a descriptive exclusion reason.

    This function deliberately does not inspect GH PORTS.
    PORTS-based preservation remains a separate decision.
    """
    info = mame.get(machine)

    if not isinstance(info, dict):
        return "missing_mame_machine"

    if info.get("cloneof"):
        return "clone"

    if _mame_flag(info.get("isbios")):
        return "bios"

    if _mame_flag(info.get("isdevice")):
        return "device"

    snaps = snaps_classifications.get(machine)

    if not isinstance(snaps, dict):
        return "missing_snaps_classification"

    if snaps.get("group") != "Arcade":
        return "non_arcade"

    gh = gh_classifications.get(machine, {})
    if not isinstance(gh, dict):
        gh = {}

    status = gh.get("game_status", "unknown")

    if status == "no_game":
        return "non_game"

    if status != "game":
        return "unknown_game_status"

    category = snaps.get("category", "")

    if category in EXCLUDED_ARCADE_CATEGORIES:
        return "excluded_snaps_category"

    machine_type = str(gh.get("type") or "").casefold()

    if any(
        term in machine_type
        for term in EXCLUDED_MACHINE_TYPE_TERMS
    ):
        return "excluded_machine_type"

    if _mame_flag(info.get("ismechanical")):
        return "mechanical"

    return "eligible"


def build_snaps_eligible_parents(
    mame: dict,
    gh_classifications: dict,
    snaps_classifications: dict,
) -> set[str]:
    """Build normal arcade eligibility without inspecting PORTS."""
    return {
        machine
        for machine in mame
        if snaps_eligibility_reason(
            machine,
            mame,
            gh_classifications,
            snaps_classifications,
        ) == "eligible"
    }
