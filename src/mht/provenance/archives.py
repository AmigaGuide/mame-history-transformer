from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from mht.utils.logger import setup_logger
from mht.utils.paths import (
    DATA_DIR,
    ensure_release_dirs,
    release_root,
    archives_dir,
    extracted_dir,
    active_version,
    incoming_dir as incoming_dir_path,
)
from mht.provenance.peek import peek_path, derive_mame_version_hint_from_filename
from mht.utils.strings import digits_score


log = setup_logger()


# ---------------------------
# Public high-level functions
# ---------------------------

def import_incoming_archives(
    *,
    incoming: Path | None = None,
    extract: bool = False,
    version: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Scan data/incoming (or a provided dir) for ZIPs, decide target MAME release per ZIP,
    and move them into releases/<ver>/archives/. Optionally extract canonical files.

    Version resolution per ZIP:
      1) Forced `version` if provided
      2) Filename hint (e.g. mame0281lx.zip -> '0281')
      3) MAME build from peek (if any)
      4) Fallback to active_version()
    """
    incoming_dir = Path(incoming) if incoming is not None else (DATA_DIR / "incoming")
    quarantine_dir = DATA_DIR / "quarantine"
    results: List[Dict[str, Any]] = []

    if not incoming_dir.exists():
        log.info("No incoming dir found at %s", incoming_dir.as_posix())
        return results

    # Only consider *.zip (case-insensitive) using glob for reliability
    zips = sorted(incoming_dir.glob("*.zip")) + sorted(incoming_dir.glob("*.ZIP"))
    for p in zips:
        if not p.is_file():
            continue

        info: Dict[str, Any] = {
            "name": p.name,
            "path": p.as_posix(),
            "action": "skipped",
            "reason": "",
            "version": None,
        }

        # Resolve version: forced → filename hint → peek → active
        target_version = version or derive_mame_version_hint_from_filename(p.name)
        if not target_version:
            meta = peek_path(p)
            if meta.get("kind") != "zip" or meta.get("error"):
                info.update({"action": "quarantined", "reason": "not_a_zip_or_bad_zip"})
                dest_q = _safe_move(p, (quarantine_dir / p.name))
                info["dest_archive"] = dest_q.as_posix()
                results.append(info)
                continue
            m_build = (meta.get("mame_xml_probe") or {}).get("mame_build")
            target_version = _folder_version_from_mame_build(m_build) or active_version()

        ensure_release_dirs(target_version)
        dest_archives_dir = (DATA_DIR / "releases" / target_version / "archives")
        dest_archives_dir.mkdir(parents=True, exist_ok=True)
        dest_archives = dest_archives_dir / p.name

        _safe_move(p, dest_archives)

        info.update({
            "action": "moved",
            "version": target_version,
            "dest_archive": dest_archives.as_posix(),
        })

        # Optional extraction (unchanged behaviour)
        if extract:
            try:
                x = _extract_canonical_files(dest_archives, target_version)
                info["extraction"] = x
            except Exception as e:
                info["extract_error"] = f"{type(e).__name__}: {e}"

        results.append(info)

    return results

# ---------------------------
# Core per-archive workflow
# ---------------------------

def _handle_one_archive(
    zip_path: Path,
    *,
    quarantine_dir: Path,
    extract: bool,
    forced_version: Optional[str] = None,
) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "path": zip_path.as_posix(),
        "action": "skipped",
        "reason": "",
        "version": None,
    }

    # Resolve target version: forced → filename hint → peek MAME build → active
    target_version = forced_version or derive_mame_version_hint_from_filename(zip_path.name)
    if not target_version:
        meta = peek_path(zip_path)
        if meta.get("kind") != "zip" or meta.get("error"):
            info.update({"action": "quarantined", "reason": "not_a_zip_or_bad_zip"})
            _safe_move(zip_path, (quarantine_dir / zip_path.name))
            info["dest_archive"] = (quarantine_dir / zip_path.name).as_posix()
            return info
        m_build = (meta.get("mame_xml_probe") or {}).get("mame_build")
        target_version = _folder_version_from_mame_build(m_build) or active_version()

    # Stage under releases/<target_version>/archives/ (build path explicitly)
    ensure_release_dirs(target_version)
    dest_archives_dir = (DATA_DIR / "releases" / target_version / "archives")
    dest_archives_dir.mkdir(parents=True, exist_ok=True)
    dest_archives = dest_archives_dir / zip_path.name

    _safe_move(zip_path, dest_archives)

    info.update({
        "action": "moved",
        "version": target_version,
        "dest_archive": dest_archives.as_posix(),
    })
    return info

# ---------------------------
# Canonical extraction
# ---------------------------

_CANON_INI_GAME = "[GAMING HISTORY] Game Or No Game.ini"
_CANON_INI_CAT  = "[GAMING HISTORY] Machine Category.ini"
_CANON_INI_TYPE = "[GAMING HISTORY] Machine Type.ini"

def _extract_canonical_files(archive_path: Path, version: str) -> Dict[str, Any]:
    """
    Extracts key files from the ZIP into releases/<ver>/extracted/ using canonical names:
      - MAME XML           -> mame.xml
      - History XML        -> history.xml              (if present)
      - GH INIs (3 files)  -> their canonical filenames

    Heuristics:
      - Choose MAME XML candidate using the same rules as peek.py
      - Prefer exact 'history.xml' for History (fallback to best xml)
      - Copy bytes; do not overwrite an existing file if same content (light SHA compare would be nicer later)
    """
    out: Dict[str, Any] = {"mame_xml": None, "history_xml": None, "inis": {}}
    target_dir = extracted_dir(version)
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path) as zf:
            # Decide candidates (reuse the simple rules inline)
            m_candidate = _choose_match(zf, prefer="mame")
            h_candidate = _choose_match(zf, prefer="history")

            # MAME XML → mame.xml (required)
            if m_candidate:
                target = target_dir / "mame.xml"
                _write_member_if_new(zf, m_candidate, target)
                out["mame_xml"] = target.as_posix()

            # History XML → history.xml (optional)
            if h_candidate:
                target = target_dir / "history.xml"
                _write_member_if_new(zf, h_candidate, target)
                out["history_xml"] = target.as_posix()

            # INIs (optional; extract when found)
            ini_map = {
                _CANON_INI_GAME: None,
                _CANON_INI_CAT:  None,
                _CANON_INI_TYPE: None,
            }

            for zi in zf.infolist():
                nm = Path(zi.filename).name
                if nm in ini_map:
                    target = target_dir / nm
                    _write_member_if_new(zf, zi, target)
                    ini_map[nm] = target.as_posix()

            out["inis"] = ini_map

    except zipfile.BadZipFile:
        out["error"] = "bad_zip_file"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"

    return out


def _choose_match(zf: zipfile.ZipFile, *, prefer: str) -> Optional[zipfile.ZipInfo]:
    """
    Pick a 'best' member for MAME or History XML.
    prefer="mame" or "history".
    """
    xmls = [zi for zi in zf.infolist() if zi.filename.lower().endswith(".xml")]
    if not xmls:
        return None

    if prefer == "history":
        # exact 'history.xml' first, then filenames containing 'history'
        exact = [zi for zi in xmls if Path(zi.filename).name.lower() == "history.xml"]
        if exact:
            return exact[0]
        hist = [zi for zi in xmls if "history" in zi.filename.lower()]
        if hist:
            # shorter filename wins
            hist.sort(key=lambda z: len(Path(z.filename).name))
            return hist[0]
        # fallback to any xml
        xmls.sort(key=lambda z: len(Path(z.filename).name))
        return xmls[0]

    # prefer == "mame"
    # names containing 'mame' + digits are best (e.g., mame0280.xml)
    mamey = [zi for zi in xmls if "mame" in zi.filename.lower()]
    if mamey:
        mamey.sort(key=lambda z: (-digits_score(Path(z.filename).name), -len(Path(z.filename).name)))
        return mamey[0]
    # fallback: any xml
    xmls.sort(key=lambda z: (-digits_score(Path(z.filename).name), -len(Path(z.filename).name)))
    return xmls[0]


def _write_member_if_new(zf: zipfile.ZipFile, member: zipfile.ZipInfo, target: Path) -> None:
    """
    Write a ZIP member to 'target'. If target exists, overwrite unconditionally for now
    (the pipeline is deterministic and stages are stamped; future: content hash compare).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member, "r") as fh, open(target, "wb") as out:
        shutil.copyfileobj(fh, out)


# ---------------------------
# Helpers
# ---------------------------

_VER_CORE_RX = re.compile(r"(\d+(?:\.\d+)+)")

def _folder_version_from_mame_build(build: Optional[str]) -> Optional[str]:
    """
    From a MAME build string (e.g. '0.280 (mame0280)'), derive the folder token:
      '0280', '0263', etc.
    Strategy:
      - grab first dotted version like 0.280
      - remove dot(s) and left-pad to 4 with zeros
    """
    if not build:
        return None
    m = _VER_CORE_RX.search(build)
    if not m:
        return None
    core = m.group(1)  # e.g., "0.280"
    digits = core.replace(".", "")
    if not digits.isdigit():
        return None
    # Pad to 4 (covers 0.80 -> 0080, 0.263 -> 0263). If longer, keep as-is.
    return digits.zfill(4)


def _safe_move(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    final = dst
    n = 1
    while final.exists():
        final = dst.with_name(f"{dst.stem}__dup{n}{dst.suffix}")
        n += 1
    shutil.move(str(src), str(final))
    return final

# --- Incoming helpers ---------------------------------------------------------
def list_incoming_archives(incoming_dir: Path | None = None) -> list[Path]:
    """
    Return a list of *.zip files in the incoming drop-zone.
    If incoming_dir is None, use the standard data/incoming path.
    """
    base = incoming_dir if incoming_dir is not None else incoming_dir_path()
    if not base.exists():
        return []
    return sorted([p for p in base.iterdir() if p.is_file() and p.suffix.lower() == ".zip"])


def verify_and_stage_zip(zip_path: Path, version: str | None = None, quarantine_dir: Path | None = None) -> Path | None:
    """
    Very light "verify" + stage:
      - ensure it's a .zip and exists
      - choose a target version (explicit -> hint from filename -> active_version())
      - ensure release dirs exist
      - copy the zip into data/releases/<ver>/archives/

    Returns the release_root(<ver>) on success; moves to quarantine and returns None on failure.
    """
    try:
        if not isinstance(zip_path, Path):
            zip_path = Path(zip_path)
        if not zip_path.exists() or zip_path.suffix.lower() != ".zip":
            raise ValueError(f"Not a .zip or missing: {zip_path}")

        v = (version or derive_mame_version_hint_from_filename(zip_path.name) or active_version()).strip()
        ensure_release_dirs(v)

        dest = archives_dir(v) / zip_path.name
        # copy (not move) so user retains their drop; adjust if you prefer move
        shutil.copy2(zip_path, dest)

        return release_root(v)

    except Exception:
        # quarantine on any failure
        try:
            qdir = quarantine_dir or (DATA_DIR / "quarantine")
            qdir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(zip_path), str(qdir / zip_path.name))
        except Exception:
            pass
        return None


_FILENAME_VER_RX = re.compile(r"(?:mame0*|history0*)(\d{2,4})", re.IGNORECASE)

def _version_key_from_filename(name: str) -> str | None:
    """
    Extract a 3–4 digit version key from common names:
      - mame0281lx.zip -> 0281
      - history281.zip / history281a.zip -> 0281
    Returns None if not recognised.
    """
    m = _FILENAME_VER_RX.search(name or "")
    if not m:
        return None
    digits = m.group(1)  # '281' or '0281'
    return digits.zfill(4)

def _safe_stage(src: Path, dst: Path) -> tuple[str, Path]:
    """
    Stage 'src' to 'dst'. If 'dst' already exists, don't create a duplicate;
    treat it as a skip and keep the canonical filename.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return ("skipped", dst)
    import shutil
    shutil.move(str(src), str(dst))
    return ("moved", dst)

def _posix(s: str | Path) -> str:
    return s.as_posix() if isinstance(s, Path) else s.replace("\\", "/")


# Export the names the CLI imports
__all__ = list(set([
    *globals().get("__all__", []),
    "list_incoming_archives",
    "verify_and_stage_zip",
    "import_incoming_archives",
]))
