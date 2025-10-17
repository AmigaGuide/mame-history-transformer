from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ----------------------------
# Public API (main entrypoints)
# ----------------------------

def peek_path(p: Path) -> Dict[str, Any]:
    """
    Inspect a single path (ZIP or loose file) without mutating disk.

    Returns a dict with keys like:
      {
        "path": "...",
        "kind": "zip" | "mame_xml" | "history_xml" | "ini" | "unknown",
        "size": int,
        "level1": { ... shallow file facts ... },
        "level2": { ... minimal structure facts ... },   # present when XML
        "level3": { ... versions & sanity flags ... },   # present when XML
        "zip_members": [ {name, size, crc, date_time, is_xml, is_ini, mame_xml_guess, history_xml_guess}, ... ]  # only for ZIP
      }
    """
    p = Path(p)
    out: Dict[str, Any] = {
        "path": p.as_posix(),
        "exists": p.exists(),
        "size": p.stat().st_size if p.exists() else None,
        "kind": "unknown",
    }
    if not p.exists() or not p.is_file():
        return out

    suffix = p.suffix.lower()

    # ZIP?
    if suffix == ".zip":
        out["kind"] = "zip"
        out.update(_peek_zip(p))
        return out

    # Loose files: triage by suffix then sniff content
    if suffix == ".xml":
        # Could be MAME or GH History
        k, lvl2, lvl3 = _peek_loose_xml(p)
        out["kind"] = k
        if lvl2:
            out["level2"] = lvl2
        if lvl3:
            out["level3"] = lvl3
        return out

    if suffix == ".ini":
        return {
            **out,
            "kind": "ini",
            "level1": _level1_basic(p),
            "level2": {
                "has_header_hint": _ini_has_mame_header_hint(p),
            },
            "level3": {
                "probable_mame_version": _ini_extract_mame_version_header(p),
            },
        }

    # Fallback: unknown single file
    out["level1"] = _level1_basic(p)
    return out


def peek_incoming_dir(incoming_dir: Path) -> List[Dict[str, Any]]:
    """
    Shallow-scan an 'incoming' directory and peek each file.
    Read-only and safe to run often.
    """
    incoming_dir = Path(incoming_dir)
    results: List[Dict[str, Any]] = []
    if not incoming_dir.exists():
        return results
    for p in sorted(incoming_dir.iterdir()):
        if p.is_file():
            results.append(peek_path(p))
    return results


# -----------------
# ZIP-level peeking
# -----------------

_XML_CAND_RX = re.compile(r"\.xml\Z", re.IGNORECASE)
_INI_CAND_RX = re.compile(r"\.ini\Z", re.IGNORECASE)

def _peek_zip(p: Path) -> Dict[str, Any]:
    """
    Level 1–3 view of a ZIP without extracting.
    - Lists members & light metadata
    - Flags likely MAME XML and History XML candidates
    - For the BEST candidate of each, opens a stream and performs minimal XML root sniff
    """
    zmeta: Dict[str, Any] = {
        "zip_members": [],
        "level1": _level1_basic(p),
        "mame_xml_candidate": None,
        "history_xml_candidate": None,
        "mame_xml_probe": None,
        "history_xml_probe": None,
    }

    try:
        with zipfile.ZipFile(p) as zf:
            # Member inventory
            for zi in zf.infolist():
                entry = {
                    "name": zi.filename,
                    "size": zi.file_size,
                    "crc": zi.CRC,
                    "date_time": _safe_datetime_tuple(zi.date_time),
                    "is_xml": bool(_XML_CAND_RX.search(zi.filename)),
                    "is_ini": bool(_INI_CAND_RX.search(zi.filename)),
                }
                # heuristics: likely mame xml name often contains 'mame' + digits, history often 'history'
                lower = zi.filename.lower()
                entry["mame_xml_guess"] = entry["is_xml"] and ("mame" in lower)
                entry["history_xml_guess"] = entry["is_xml"] and ("history" in lower)

                zmeta["zip_members"].append(entry)

            # Pick best candidates
            mame_cand = _choose_best_mame_member(zmeta["zip_members"])
            hist_cand = _choose_best_history_member(zmeta["zip_members"])

            zmeta["mame_xml_candidate"] = mame_cand
            zmeta["history_xml_candidate"] = hist_cand

            # Probe candidates (root-only / tiny iterations)
            if mame_cand:
                with zf.open(mame_cand["name"], "r") as fh:
                    zmeta["mame_xml_probe"] = _probe_mame_xml_stream(fh)

            if hist_cand:
                with zf.open(hist_cand["name"], "r") as fh:
                    zmeta["history_xml_probe"] = _probe_history_xml_stream(fh)

    except zipfile.BadZipFile:
        zmeta["error"] = "bad_zip_file"
    except Exception as e:
        zmeta["error"] = f"{type(e).__name__}: {e}"

    return zmeta


def _choose_best_mame_member(members: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # Prefer xml with 'mame' in name, then any xml, then None
    cands = [m for m in members if m.get("is_xml")]
    cands_mame = [m for m in cands if m.get("mame_xml_guess")]
    if cands_mame:
        # prefer longer filenames with digits (e.g., mame0280.xml)
        cands_mame.sort(key=lambda m: (-_digits_score(m["name"]), -len(m["name"])))
        return cands_mame[0]
    if cands:
        # fallback: any xml
        cands.sort(key=lambda m: (-_digits_score(m["name"]), -len(m["name"])))
        return cands[0]
    return None


def _choose_best_history_member(members: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    cands = [m for m in members if m.get("is_xml")]
    cands_hist = [m for m in cands if m.get("history_xml_guess")]
    if cands_hist:
        # history.xml is typically smallish; prefer exact name if present
        cands_hist.sort(key=lambda m: (0 if Path(m["name"]).name.lower() == "history.xml" else 1, len(m["name"])))
        return cands_hist[0]
    if cands:
        # fallback: any xml
        cands.sort(key=lambda m: (0 if Path(m["name"]).name.lower() == "history.xml" else 1, len(m["name"])))
        return cands[0]
    return None


def _digits_score(s: str) -> int:
    return sum(ch.isdigit() for ch in s)


def _safe_datetime_tuple(dt: Tuple[int, int, int, int, int, int]) -> str:
    try:
        y, m, d, hh, mm, ss = dt
        return f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}:{ss:02d}"
    except Exception:
        return "unknown"


# --------------------------
# Loose XML probing (levels)
# --------------------------

def _peek_loose_xml(p: Path) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """
    Decide if loose XML is MAME or History by sniffing root.
    Returns (kind, level2, level3)
    """
    # Root-only probe
    try:
        for event, elem in ET.iterparse(p, events=("start",)):
            tag = elem.tag.lower()
            if tag == "mame":
                lvl2, lvl3 = _level23_mame_xml(p)
                return "mame_xml", lvl2, lvl3
            if tag == "history":
                lvl2, lvl3 = _level23_history_xml(p)
                return "history_xml", lvl2, lvl3
            # Unknown root → stop early
            break
    except ET.ParseError as e:
        return "unknown", {"parse_error": str(e)}, {}
    except Exception as e:
        return "unknown", {"error": f"{type(e).__name__}: {e}"}, {}

    return "unknown", {"note": "unrecognised XML root"}, {}


def _level1_basic(p: Path) -> Dict[str, Any]:
    st = p.stat()
    return {
        "size_bytes": st.st_size,
        "modified": st.st_mtime,
        "name": p.name,
        "suffix": p.suffix.lower(),
    }


# ---- MAME XML ----

def _level23_mame_xml(p: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Level 2/3 info for a MAME XML file by streaming minimal parts."""
    lvl2: Dict[str, Any] = {}
    lvl3: Dict[str, Any] = {}
    # Root attributes
    build, mameconfig = None, None
    try:
        for event, elem in ET.iterparse(p, events=("start",)):
            if elem.tag.lower() == "mame":
                build = elem.attrib.get("build")
                mameconfig = elem.attrib.get("mameconfig")
                lvl3["mame_build"] = build
                if mameconfig is not None:
                    lvl3["mameconfig"] = mameconfig
                break
    except Exception as e:
        lvl2["error"] = f"{type(e).__name__}: {e}"
        return lvl2, lvl3

    # Minimal structure peek: count until we see both a parent and a clone
    parent_seen = False
    clone_seen = False
    machine_sample = 0
    try:
        for event, elem in ET.iterparse(p, events=("end",)):
            if event == "end" and elem.tag == "machine":
                cloneof = elem.attrib.get("cloneof")
                if cloneof:
                    clone_seen = True
                else:
                    parent_seen = True
                machine_sample += 1
                elem.clear()
                if parent_seen and clone_seen:
                    break
                if machine_sample >= 3000:
                    # safety valve; we learned enough
                    break
    except Exception as e:
        lvl2["scan_error"] = f"{type(e).__name__}: {e}"

    lvl2.update({
        "sampled_machines": machine_sample,
        "observed_parent": parent_seen,
        "observed_clone": clone_seen,
    })
    return lvl2, lvl3


def _probe_mame_xml_stream(fh) -> Dict[str, Any]:
    """Root-only probe for MAME XML inside ZIP (file-like object)."""
    out: Dict[str, Any] = {}
    try:
        # Parse only the first start event
        for event, elem in ET.iterparse(_rewindable(fh), events=("start",)):
            if elem.tag.lower() == "mame":
                out["mame_build"] = elem.attrib.get("build")
                if "mameconfig" in elem.attrib:
                    out["mameconfig"] = elem.attrib.get("mameconfig")
                break
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# ---- History XML ----

def _level23_history_xml(p: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Level 2/3 info for a History XML file by scanning a tiny subset."""
    lvl2: Dict[str, Any] = {}
    lvl3: Dict[str, Any] = {}

    # Root attributes (version/date)
    version, date = None, None
    try:
        for event, elem in ET.iterparse(p, events=("start",)):
            if elem.tag.lower() == "history":
                version = elem.attrib.get("version")
                date = elem.attrib.get("date")
                lvl3["history_version"] = version
                lvl3["history_date"] = date
                break
    except Exception as e:
        lvl2["error"] = f"{type(e).__name__}: {e}"
        return lvl2, lvl3

    # Minimal structure: require at least one <systems> and one <software> entry overall.
    has_systems = False
    has_software = False
    entries_scanned = 0
    try:
        for event, elem in ET.iterparse(p, events=("end",)):
            if event == "end" and elem.tag == "entry":
                # cheap classification
                kinds = {c.tag for c in elem}
                if "systems" in kinds:
                    has_systems = True
                if "software" in kinds:
                    has_software = True
                entries_scanned += 1
                elem.clear()
                if has_systems and has_software:
                    break
                if entries_scanned >= 10000:
                    # safety: very large file; we’ve looked enough
                    break
    except Exception as e:
        lvl2["scan_error"] = f"{type(e).__name__}: {e}"

    lvl2.update({
        "observed_system_entry": has_systems,
        "observed_software_entry": has_software,
        "entries_sampled": entries_scanned,
        "meets_minimum_shape": bool(has_systems and has_software),
    })
    return lvl2, lvl3


def _probe_history_xml_stream(fh) -> Dict[str, Any]:
    """Root-only probe for History XML inside ZIP (file-like object)."""
    out: Dict[str, Any] = {}
    try:
        for event, elem in ET.iterparse(_rewindable(fh), events=("start",)):
            if elem.tag.lower() == "history":
                out["history_version"] = elem.attrib.get("version")
                out["history_date"] = elem.attrib.get("date")
                break
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


# -------------
# INI helpers
# -------------

_HDR_VER_RX = re.compile(r"for\s+MAME\s+([0-9]+\.[0-9A-Za-z._-]+)", re.IGNORECASE)

def _ini_has_mame_header_hint(p: Path) -> bool:
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                if "for MAME" in line:
                    return True
    except Exception:
        pass
    return False


def _ini_extract_mame_version_header(p: Path) -> Optional[str]:
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                m = _HDR_VER_RX.search(line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


# -----------------------
# Utility: rewind wrapper
# -----------------------

def _rewindable(file_like) -> io.BytesIO:
    """
    Take a file-like (as provided by ZipFile.open) and return a rewindable buffer
    with only the prefix needed for ElementTree to see the root.
    """
    # Read a small chunk — XML root and prolog are at the start. 64 KiB is generous.
    head = file_like.read(65536)
    return io.BytesIO(head)

# ---------------------------------------------------------------------
# Adapters expected by cli.py (back-compat shims)
# ---------------------------------------------------------------------
from pathlib import Path as _Path

# If your internal function names differ, just swap the right targets below.
# For example, if you use class-based sniffers, instantiate and call them here.

def sniff_mame_xml(path: _Path, **kwargs) -> dict:
    """
    Back-compat wrapper expected by mht.cli.
    Delegates to your existing MAME XML peek function.
    """
    # CHANGE the target below to match your actual function/class:
    return peek_mame_xml(_Path(path), **kwargs)  # noqa: F821

def sniff_history_xml(path: _Path, **kwargs) -> dict:
    """
    Back-compat wrapper expected by mht.cli.
    Delegates to your existing History XML peek function.
    """
    # CHANGE the target below to match your actual function/class:
    return peek_history_xml(_Path(path), **kwargs)  # noqa: F821

def sniff_ini_file(path: _Path, *, encoding: str | None = None, header_lines: int = 16, **kwargs) -> dict:
    """
    Back-compat wrapper expected by mht.cli.
    Delegates to your existing INI header peek function.
    """
    # CHANGE the target below to match your actual function/class:
    return peek_ini_header(_Path(path), encoding=encoding, header_lines=header_lines, **kwargs)  # noqa: F821

def derive_mame_version_hint_from_filename(name: str | Path) -> str | None:
    """
    Best-effort MAME version hint from a filename like:
      - mame0280lx.zip / mame0280.xml     -> '0280'
      - mame0263.zip                       -> '0263'
      - mame-0.279-win.zip                 -> '0279'
      - mame281.zip                        -> '0281' (leading 0 added)
    Returns None if no obvious hint is found.
    """
    s = Path(name).name.lower()

    # Forms like mame0280*, mame263, mame-0281, mame_0280, etc.
    m = re.search(r"mame[-_]?0?(\d{3,4})(?!\d)", s)
    if m:
        g = m.group(1)
        return g.zfill(4) if g else None

    # Decimal forms like 0.280 / 0.263 (ensure not part of a larger number)
    m2 = re.search(r"(?<!\d)0\.(\d{3})(?!\d)", s)
    if m2:
        return f"0{m2.group(1)}"

    # Fallback: 1.234 -> 1234 (rare, but keep just in case)
    m3 = re.search(r"(?<!\d)(\d)\.(\d{3})(?!\d)", s)
    if m3:
        return f"{m3.group(1)}{m3.group(2)}".zfill(4)

    return None

# (Optional) make sure these names are exported if you maintain __all__
try:
    __all__  # type: ignore[name-defined]
except NameError:
    __all__ = []
