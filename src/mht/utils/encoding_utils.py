"""
Filename: encoding_utils.py
Author: XtC

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Detect the text encoding of a file using the `chardet` library. This module is
deliberately narrow in scope: it does not handle caching, version tracking, or
fallback logic—only detection.

Key behaviours:
- Reads file bytes and returns `chardet.detect(...).get('encoding')` or "Unknown".
- Emits lightweight debug logs for traceability.

Exports:
- detect_encoding(file_path: Path) -> str

Licence:
This file forms part of a student project and is not intended for commercial use.
See repository LICENCE for details.
"""

from __future__ import annotations

from pathlib import Path
import chardet
from typing import Any, Dict, Optional, Tuple
import io
import re
import time
import zipfile
import xml.etree.ElementTree as ET
import datetime

from mht.utils.logger import debug_log, setup_logger
from mht.utils.config import LOG_LEVEL


__all__ = ["detect_encoding", "detect_encodings_from_archives"]

log = setup_logger(log_level=LOG_LEVEL)

_XML_DECL_RX = re.compile(rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def detect_encoding(file_path: Path) -> str:
    """
    Detect the encoding of a file using `chardet`.

    Parameters:
        file_path: Path to the XML/INI (or other text) file.

    Returns:
        Detected encoding label (e.g. "UTF-8", "windows-1252"), or "Unknown" if
        chardet does not provide an encoding.
    """
    debug_log(f"Detecting encoding for: {file_path.name}")

    with open(file_path, "rb") as f:
        raw_data = f.read()
        result = chardet.detect(raw_data)
        encoding = result.get("encoding") or "Unknown"

    debug_log(f"Detected encoding for {file_path.name}: {encoding}")
    return encoding


# ========================= ZIP-ONLY FULL-FILE DETECTION =========================
# Central entry point for encoding/version detection directly from archives.
# Scans the FIVE artefacts once per new release:
#   - MAME XML (from MAME archive)
#   - History XML (from GH archive)
#   - 3 x GH INIs (from GH archive)
#
# It returns a fresh encodings dictionary keyed by the canonical leaf names your
# pipeline already uses:
#   "mame.xml", "history.xml",
#   "[GAMING HISTORY] Game Or No Game.ini",
#   "[GAMING HISTORY] Machine Category.ini",
#   "[GAMING HISTORY] Machine Type.ini"
#
# Downstream stages continue to look up encodings by these keys.

def detect_encoding_bytes(raw_data: bytes) -> str:
    """Detect encoding for an in-memory byte buffer using chardet."""
    result = chardet.detect(raw_data or b"")
    return (result.get("encoding") or "Unknown")

def _normalise_label(label: Optional[str]) -> Tuple[str, bool]:
    """
    Normalise common aliases; collapse ASCII to utf-8 and return (encoding, ascii_only).
    """
    if not label:
        return ("utf-8", False)
    l = label.strip().lower()
    alias = {
        "utf8": "utf-8",
        "us-ascii": "ascii",
        "ansi_x3.4-1968": "ascii",
        "cp1252": "windows-1252",
        "latin1": "iso-8859-1",
    }
    l = alias.get(l, l)
    if l == "ascii":
        return ("utf-8", True)  # ASCII ⊂ UTF-8; treat operationally as UTF-8
    return (l, False)

def _bom_hint(raw: bytes) -> Optional[str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8"
    if raw.startswith(b"\xff\xfe\x00\x00") or raw.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    return None

def _xml_decl_hint(raw: bytes) -> Optional[str]:
    m = _XML_DECL_RX.search(raw[:4096])  # decl is always at the start
    if m:
        try:
            return m.group(1).decode("ascii", "strict")
        except Exception:
            return None
    return None

def _xml_root_version_from_bytes(raw: bytes) -> Dict[str, Optional[str]]:
    """
    Return {'build': ..., 'version': ...} if present on root (mame/history).
    """
    try:
        # Parse from memory; we don't need full iterparse for this
        for event, elem in ET.iterparse(io.BytesIO(raw), events=("start",)):
            tag = elem.tag.lower()
            if tag in ("mame", "history"):
                return {
                    "build": elem.attrib.get("build"),
                    "version": elem.attrib.get("version"),
                }
            # Break after first start tag seen (root)
            break
    except Exception:
        pass
    return {"build": None, "version": None}

def _ini_version_from_bytes(raw: bytes, enc: str) -> Dict[str, Optional[str]]:
    """
    Use your stream-friendly ini_version_info() by wrapping a BytesIO with TextIO.
    """
    try:
        from mht.utils.ini import ini_version_info
        text = io.TextIOWrapper(io.BytesIO(raw[:16384]), encoding=enc or "utf-8", errors="replace")
        meta = ini_version_info(text) or {}
        # Normalise to your version_record style in main later; here we just pass raw fields through
        return {
            "mame_version": meta.get("mame_version"),
            "generated_date_raw": meta.get("generated_date_raw"),
            "generated_date": meta.get("generated_date"),
        }
    except Exception:
        return {"mame_version": None, "generated_date_raw": None, "generated_date": None}

def _zip_member_map(zp: Path) -> Dict[str, str]:
    """
    Create a case-insensitive leaf -> full member path map.
    """
    mapping: Dict[str, str] = {}
    with zipfile.ZipFile(zp) as zf:
        for zinfo in zf.infolist():
            leaf = Path(zinfo.filename).name
            if not leaf:
                continue
            ll = leaf.lower()
            if ll not in mapping:
                mapping[ll] = zinfo.filename
    return mapping

def _read_all(zp: Path, member: str) -> Tuple[bytes, int, int]:
    """
    Read an entire member: returns (raw_bytes, crc32, uncompressed_size).
    """
    with zipfile.ZipFile(zp) as zf:
        zinfo = zf.getinfo(member)
        with zf.open(zinfo, "r") as bf:
            raw = bf.read()
        return raw, zinfo.CRC, zinfo.file_size

# --- Helpers for cache-aware comparison (stable fields only) -------------------

def _utc_now() -> str:
    """Return an ISO8601 UTC timestamp with a 'Z' suffix."""
    return datetime.datetime.utcnow().isoformat() + "Z"

def _member_signature(zip_archive: Path, member_fullpath: str, crc32: int, size: int) -> dict:
    """
    Stable identity for a ZIP member.
    We keep the archive's *filename* for equality checks and also store the
    full path purely for provenance (not used in signature matching).
    """
    return {
        "zip_archive": zip_archive.name,                # used for matching
        "zip_archive_path": zip_archive.as_posix(),     # provenance only
        "zip_member": member_fullpath,                  # used for matching
        "zip_crc32": int(crc32),                        # used for matching
        "zip_size_bytes": int(size),                    # used for matching
    }

def _signatures_match(a: dict, b: dict) -> bool:
    """True if the two signature dicts represent the same underlying bytes."""
    keys = ("zip_archive", "zip_member", "zip_crc32", "zip_size_bytes")
    return all((a or {}).get(k) == (b or {}).get(k) for k in keys)

def _stable_changed(prev: dict | None, new: dict) -> bool:
    """
    Decide whether the record changed, ignoring volatile fields like timings or confidence.
    We compare only these stable fields:
      - encoding, detected_via
      - zip_archive, zip_member, zip_crc32, zip_size_bytes
      - xml_decl_encoding, xml_bom (for XML)
    """
    prev = prev or {}
    keys = (
        "encoding", "detected_via",
        "zip_archive", "zip_member", "zip_crc32", "zip_size_bytes",
        "xml_decl_encoding", "xml_bom",
    )
    return any((prev.get(k) != new.get(k)) for k in keys)

def _zipinfo(archive: Path, member_fullpath: str) -> zipfile.ZipInfo:
    with zipfile.ZipFile(archive) as zf:
        return zf.getinfo(member_fullpath)

# --- Main: cache-aware, single-pass chardet, ZIP-only full-file detection -----

def detect_encodings_from_archives(
    mame_archive: Path,
    history_archive: Path,
    canonical_leaves: Dict[str, str],
    prior: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], bool]:
    """
    Full-file detection from the two ZIPs with cache-aware short-circuiting.

    Behaviour:
    - Resolve members deterministically.
    - Build a ZIP member signature (archive, member path, crc32, size).
    - If the signature matches the prior cache record for this leaf name,
      reuse the cached record and SKIP re-scanning.
    - Otherwise, read the whole member once and determine encoding by precedence:
         BOM -> XML declaration (XML only) -> chardet.detect(raw) [single call].
    - Record rich metadata; normalise ASCII to 'utf-8' with ascii_only flag.
    - Return the updated encodings dict and a boolean indicating if cache changed
      (based on stable fields only).
    """
    log.info("Beginning full-file encoding detection from ZIPs (first run per release can take minutes)…")
    t_global = time.perf_counter()
    prior = prior or {}
    out: Dict[str, Any] = dict(prior)  # carry forward unrelated entries
    changed = False

    # ------- Resolve members deterministically
    mame_map = _zip_member_map(mame_archive)
    hist_map = _zip_member_map(history_archive)

    # MAME XML member (first *.xml)
    mame_xml_member = next((p for p in mame_map.values() if p.lower().endswith(".xml")), None)
    if not mame_xml_member:
        raise FileNotFoundError(f"No XML found in {mame_archive.name}")

    # History XML member (prefer history/history.xml)
    pref_lower = "history/history.xml"
    inv_hist = {v.lower(): v for v in hist_map.values()}
    hist_xml_member = inv_hist.get(pref_lower, None)
    if not hist_xml_member:
        hist_xml_member = next((p for p in hist_map.values() if p.lower().endswith(".xml")), None)
    if not hist_xml_member:
        raise FileNotFoundError(f"No history XML found in {history_archive.name}")

    # INIs by canonical basenames (tolerate folder prefixes)
    ini_game_leaf     = canonical_leaves["ini_game"].lower()
    ini_category_leaf = canonical_leaves["ini_category"].lower()
    ini_type_leaf     = canonical_leaves["ini_type"].lower()
    hist_by_leaf = {Path(v).name.lower(): v for v in hist_map.values()}
    ini_members = {
        canonical_leaves["ini_game"]:     hist_by_leaf.get(ini_game_leaf),
        canonical_leaves["ini_category"]: hist_by_leaf.get(ini_category_leaf),
        canonical_leaves["ini_type"]:     hist_by_leaf.get(ini_type_leaf),
    }
    missing_inis = [k for k, v in ini_members.items() if not v]
    if missing_inis:
        raise FileNotFoundError(f"Missing INI(s) in {history_archive.name}: {', '.join(missing_inis)}")

    # ------- Small worker to process a single member with cache short-circuit

    def process(
        archive: Path,
        member_fullpath: str,
        leaf_key: str,
        is_xml: bool,
    ) -> dict:
        # Build signature WITHOUT reading the file (ZipInfo has crc & size)
        zi = _zipinfo(archive, member_fullpath)
        signature = _member_signature(archive, member_fullpath, zi.CRC, zi.file_size)
        prev = out.get(leaf_key)

        # Short-circuit if signature matches prior cache record
        if prev and _signatures_match(prev, signature):
            enc = prev.get("encoding") or "utf-8"
            log.info(f"[detect] Cached: {leaf_key} → {enc} (crc/size match) — skipping analysis.")
            return prev  # reuse as-is; don't flip 'changed'

        # Otherwise, we must analyse: read entire member (with progress)
        raw, crc32, size = _read_all_with_progress(archive, member_fullpath, log_label=f"{archive.name} :: {member_fullpath}")

        # Determine encoding by precedence (log clearly so the run never looks frozen)
        bom  = _bom_hint(raw)
        decl = _xml_decl_hint(raw) if is_xml else None

        detected_via = None
        guess = None
        conf = None

        if bom:
            guess = bom
            detected_via = "bom"
            log.info(f"[detect] {leaf_key}: BOM present → using '{guess}' (no chardet run).")

        elif is_xml and decl:
            guess = decl
            detected_via = "xml_decl"
            log.warning(f"{leaf_key} declares encoding='{decl}' — provider may have changed other things; cache updated. "
                        "Skipping chardet for this file.")

        else:
            mb = len(raw) / (1024 * 1024)
            log.info(f"[detect] {leaf_key}: analysing {mb:.2f} MiB with chardet — this may take several minutes…")
            # Single chardet pass for BOTH label and confidence
            result = chardet.detect(raw or b"")
            guess = result.get("encoding") or "Unknown"
            conf  = result.get("confidence")
            log.info(f"[detect] chardet: {leaf_key} → {guess} (confidence {conf:.2f} if not None)")
            detected_via = "chardet"

        enc_final, ascii_only = _normalise_label(guess)
        if ascii_only:
            log.info(f"[detect] {leaf_key}: normalising ASCII → UTF-8 and marking ascii_only=true.")

        # Version hints while bytes are in hand
        if is_xml:
            xr = _xml_root_version_from_bytes(raw)  # {"build": ..., "version": ...}
            ini_hdr = None
        else:
            xr = None
            ini_hdr = _ini_version_from_bytes(raw, enc_final)

        detected_at = _utc_now()

        record = {
            "encoding": enc_final,
            "source": "zip",
            **signature,                      # zip_archive, zip_archive_path, zip_member, zip_crc32, zip_size_bytes
            "detected_via": detected_via,
            "chardet": {"encoding": guess, "confidence": conf} if detected_via == "chardet" else {},
            "sample_bytes": len(raw),
            "detection_time_ms": int((time.perf_counter() - t_global) * 1000),  # coarse, but fine
            "detected_at_utc": detected_at,   # ← new timestamp
            "ascii_only": ascii_only if not is_xml else False,
            # XML extras
            "xml_decl_encoding": decl if is_xml and decl else None,
            "xml_bom": bom if is_xml and bom else None,
            "xml_root_attrs": xr if is_xml else None,
            # INI extras
            "ini_header": ini_hdr if not is_xml else None,
        }

        # Flip 'changed' only if stable fields differ
        if _stable_changed(prev, record):
            nonlocal changed
            changed = True

        return record

    # ------- Process all five artefacts

    mame_leaf = canonical_leaves["mame_xml"]
    out[mame_leaf] = process(mame_archive, mame_xml_member, mame_leaf, is_xml=True)

    hist_leaf = canonical_leaves["history_xml"]
    out[hist_leaf] = process(history_archive, hist_xml_member, hist_leaf, is_xml=True)

    for leaf, member in ini_members.items():
        out[leaf] = process(history_archive, member, leaf, is_xml=False)

    # ---- Human-friendly summary line so you can see the final decisions at a glance
    def _fmt(rec: dict | None) -> str:
        if not isinstance(rec, dict):
            return "unknown"
        enc = rec.get("encoding") or "utf-8"
        if rec.get("ascii_only"):
            return f"{enc} (ascii-only)"
        return enc

    m_sum = _fmt(out.get(canonical_leaves["mame_xml"]))
    h_sum = _fmt(out.get(canonical_leaves["history_xml"]))
    g_sum = _fmt(out.get(canonical_leaves["ini_game"]))
    c_sum = _fmt(out.get(canonical_leaves["ini_category"]))
    t_sum = _fmt(out.get(canonical_leaves["ini_type"]))

    # Compact INI summary: if all three match, collapse to one label
    ini_labels = {g_sum, c_sum, t_sum}
    if len(ini_labels) == 1:
        ini_summary = next(iter(ini_labels))
        log.info(f"Encodings summary: mame.xml={m_sum}, history.xml={h_sum}, INIs={ini_summary}")
    else:
        log.info(f"Encodings summary: mame.xml={m_sum}, history.xml={h_sum}, "
                 f"GameOrNoGame={g_sum}, MachineCategory={c_sum}, MachineType={t_sum}")

    debug_log("[encodings] ZIP-only detection completed in "
              f"{time.perf_counter() - t_global:.2f}s")
    return out, changed

# Tunables for ZIP streaming
DETECT_CHUNK_BYTES = 32 * 1024 * 1024   # 32 MiB per read
PROGRESS_EVERY_MB  = 64                 # log every 64 MiB read

def _human_mb(n_bytes: int) -> float:
    return round(n_bytes / (1024 * 1024), 2)

def _read_all_with_progress(zp: Path, member: str, *, log_label: str) -> tuple[bytes, int, int]:
    """
    Read an entire ZIP member in large chunks with periodic progress logs.
    Returns (raw_bytes, crc32, uncompressed_size).
    """
    t0 = time.perf_counter()
    with zipfile.ZipFile(zp) as zf:
        zinfo = zf.getinfo(member)
        total_size = int(zinfo.file_size)
        crc32 = int(zinfo.CRC)

        read_so_far = 0
        last_report_at = 0
        chunks: list[bytes] = []

        log.info(f"[detect] {log_label}: start, { _human_mb(total_size) } MiB to scan…")
        with zf.open(zinfo, "r") as bf:
            while True:
                chunk = bf.read(DETECT_CHUNK_BYTES)
                if not chunk:
                    break
                chunks.append(chunk)
                read_so_far += len(chunk)

                # periodic progress
                if _human_mb(read_so_far) - last_report_at >= PROGRESS_EVERY_MB:
                    elapsed = max(time.perf_counter() - t0, 1e-6)
                    speed = _human_mb(read_so_far) / elapsed
                    remaining = max(total_size - read_so_far, 0)
                    eta = (remaining / (1024*1024)) / max(speed, 1e-6)
                    log.info(
                        f"[detect] {log_label}: {_human_mb(read_so_far)} / {_human_mb(total_size)} MiB "
                        f"({int(100*read_so_far/total_size)}%) at {speed:.1f} MiB/s, ETA ~{eta:.1f}s"
                    )
                    last_report_at = _human_mb(read_so_far)

        raw = b"".join(chunks)
        elapsed = time.perf_counter() - t0
        speed = _human_mb(total_size) / max(elapsed, 1e-6)
        log.info(f"[detect] {log_label}: done in {elapsed:.1f}s, avg {speed:.1f} MiB/s")
        return raw, crc32, total_size
