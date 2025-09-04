"""
Filename: transformer.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Transforms parsed artefacts into a Wiki-ready dataset.

Phase 1 (this file): Parent/clone selection based on INI classifications + Title parsing.
- Keep parents where INI: game_status == "game" AND category includes "Arcade".
- Include ALL clones of those parents (even if clone classifications are unknown).
- Parse titles per spec: titles/subtitles/versions/global_version (numbered fields).
- Do NOT use 'type' to filter (kept for description only).
- Do NOT filter isbios/isdevice/ismechanical; just report any that appear post-filter.

Inputs:
- output/mame_machines.json
- output/gh_ini_classifications.json
- output/mame_parent_index.json

Outputs:
- output/exotica_lit_wiki.json        (Wiki-ready, no Ports yet; includes parsed description object)
- data/transform_summary.json         (counts, QA diagnostics, uncapped title anomaly examples)

Returns:
- True on success, False otherwise.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Set, List, Tuple, Sequence, Iterable
import json
import datetime
import time
import re
from collections import Counter

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

# --- Schemas (bump only when shapes change) ---
TRANSFORMER_SCHEMA = "0.5"   # used in data/transform_summary.json
WIKI_SCHEMA        = "1.0"   # used in exotica_lit_wiki.json header

DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")

MAME_MACHINES_PATH = OUTPUT_DIR / "mame_machines.json"
INI_CLASS_PATH     = OUTPUT_DIR / "gh_ini_classifications.json"
PARENT_INDEX_PATH  = OUTPUT_DIR / "mame_parent_index.json"

WIKI_PREFIX = "Lost In Translation/"
WIKI_PAGES_REDIRECTS_PATH = OUTPUT_DIR / "exotica_wiki_pages_and_redirects.json"

WIKI_OUT_PATH      = OUTPUT_DIR / "exotica_lit_wiki.json"
TRANS_SUMMARY_PATH = DATA_DIR / "transform_summary.json"

_ALNUM = re.compile(r"[A-Za-z0-9]")
_INFIX_RE = re.compile(r"[A-Za-z0-9]\([^()\[\]]+\)[A-Za-z0-9]")
_VERSION_CORE_RX = re.compile(r"\d+(?:\.\d+)+")

# Display precedence for the “Plus:” line (higher = earlier).
_MEDIA_ORDER = {
    "GD-ROM": 100,
    "DVD-ROM": 90,
    "CD-ROM": 80,
    "LaserDisc": 70,
    "Capacitance Electronic Disc (CED)": 60,
    "Hard disk": 50,
    "CompactFlash card": 40,
    "Secure Digital card": 30,
    "NAND flash": 20,
    "USB storage": 10,
    "VHS tape": 0,
}

def _order_media_labels(labels: list[str]) -> list[str]:
    """Sort labels by precedence, then A→Z as a stable tiebreaker."""
    # De-dupe while preserving first occurrence (defensive)
    labels = list(dict.fromkeys(labels))
    return sorted(
        labels,
        key=lambda s: ( -_MEDIA_ORDER.get(s, -1), s.casefold() )
    )

def _normalise_device_to_media(raw: str) -> str | None:
    """
    Map one MAME device token/path to a friendly media label.
    Returns None for non-media / maintenance / bus identifiers.
    """
    s = (raw or "").lower()

    # Tokenise for exact hits (cd, dvd, cf, etc.)
    tokens = set(re.findall(r"[a-z0-9_]+", s))

    # LaserDisc: explicit names, numeric-suffixed tokens, or known player models
    if (
        "laserdisc" in tokens
        or any(t.startswith("laserdisc") for t in tokens)   # <- handles 'laserdisc1', 'laserdisc2', etc.
        or re.search(r"\b(ld_)?(ldv1000|pr7820|pr8210a?|22vp932)\b", s)
    ):
        return "LaserDisc"

    # Capacitance Electronic Disc
    if "ced_videodisc" in tokens:
        return "Capacitance Electronic Disc (CED)"

    # GD-ROM (Sega)
    if "gdrom" in tokens:
        return "GD-ROM"
    
    # DVD family (e.g., 'dvdrom', 'dvdrom1', 'dvd', etc.)
    if {"dvdrom", "dvd"} & tokens or any(t.startswith("dvdrom") for t in tokens):
        return "DVD-ROM"

    # Compact Disc family:
    #  - exact tokens like 'cdrom', 'cd', 'audiocd', 'cdxa'
    #  - drive identifiers like 'cdrom1', 'cdrom2', ...
    #  - known ATAPI/SCSI model IDs already in your list
    if (
        {"cdrom", "cd", "audiocd", "cdxa", "xm3301", "cr589", "stvcd"} & tokens
        or any(t.startswith("cdrom") for t in tokens)
    ):
        return "CD-ROM"

    # Hard disks (IDE/SCSI)
    if {"hdd", "harddisk", "scsi_hdd_image"} & tokens or ":hdd" in s:
        return "Hard disk"

    # CompactFlash (via PC Card/ATA bridges too)
    if {"cf", "cfcard", "cflash", "ataflash", "taitocf", "taitopccard1", "taitopccard2", "pccard"} & tokens:
        return "CompactFlash card"

    # Secure Digital
    if {"sdcard", "internalsd"} & tokens:
        return "Secure Digital card"

    # NAND flash
    if "nand" in tokens:
        return "NAND flash"

    # USB storage
    if "usb" in tokens:
        return "USB storage"

    # VHS tape
    if "vhs" in tokens:
        return "VHS tape"

    # Everything else (runtime, install, recovery, disks, cycraft, buses, etc.) -> ignore
    return None


def _normalise_device_list_to_media(devs: Iterable[str] | str | None) -> list[str]:
    """Return de-duplicated friendly labels, preserving original order; ignore unknowns."""
    if devs is None:
        return []
    seq = devs if isinstance(devs, (list, tuple)) else [devs]

    out: list[str] = []
    seen: set[str] = set()
    for raw in seq:
        label = _normalise_device_to_media(str(raw))
        if not label:
            continue  # drop unknown/non-media entries
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            out.append(label)
    return out



def join_with_ampersand(items: Sequence[str]) -> str:
    """Join items as: A; A & B; A, B & C (no trimming; upstream cleaned)."""
    n = len(items)
    if n == 0:
        return ""
    if n == 1:
        return items[0]
    if n == 2:
        return f"{items[0]} & {items[1]}"
    return f"{', '.join(items[:-1])} & {items[-1]}"

def _split_outside_parens(s: str) -> list[str]:
    """Split on '/' only when outside (...) groups. Leave content inside parens untouched."""
    parts, buf, depth = [], [], 0
    for ch in s or "":
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "/" and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
        else:
            buf.append(ch)
    last = "".join(buf).strip()
    if last:
        parts.append(last)
    # Do not strip—inputs already cleaned upstream
    return parts

def _format_rom_block(rom_count: int, rom_bytes_total: int,
                      disk_required: str | None, disk_regions) -> str:
                          
    # Line 1
    line1 = f"{rom_count:,} ROM" + ("" if rom_count == 1 else "s")

    # Line 2
    total_bytes = int(rom_bytes_total or 0)
    human = _bytes_to_binary_human(total_bytes)
    line2 = f"{total_bytes:,} bytes" + (f" ({human[0]:.2f} {human[1]})" if human else "")

    # Line 3 — only if disk_required == "yes"; devices come from disk_regions[]
    line3 = None
    if (disk_required or "").lower() == "yes":
        # Build the full list (including duplicates) by normalising each raw entry
        seq = disk_regions if isinstance(disk_regions, (list, tuple)) else ([disk_regions] if disk_regions else [])
        all_labels: list[str] = []
        for raw in seq:
            lab = _normalise_device_to_media(str(raw))
            if lab:
                all_labels.append(lab)

        if all_labels:
            # Count case-insensitively, but preserve original label text
            counts = Counter(l.casefold() for l in all_labels)

            # Preserve first-seen identity for later stable precedence sorting
            first_seen_unique = list(dict.fromkeys(all_labels))

            # Apply your precedence sort
            ordered_unique = _order_media_labels(first_seen_unique)

            # Render with “(Nx)” prefix when N>1, per your style “(2x) CD-ROM”
            display_labels = []
            for lab in ordered_unique:
                n = counts[lab.casefold()]
                display_labels.append(f"({n}x) {lab}" if n > 1 else lab)

            line3 = f"Plus: {join_with_ampersand(display_labels)}"

    return "\n".join([line1, line2] + ([line3] if line3 else []))


def _bytes_to_binary_human(n: int) -> tuple[float, str] | None:
    """Return (value, unit) in KiB/MiB/GiB to 2dp, or None if < 1024 bytes."""
    if n is None:
        return None
    KB = 1024
    MB = 1024 ** 2
    GB = 1024 ** 3
    if n >= GB:
        return (n / GB, "GiB")
    if n >= MB:
        return (n / MB, "MiB")
    if n >= KB:
        return (n / KB, "KiB")
    return None

def format_manufacturers_for_wiki(raw: str | None) -> str:
    parts = [p.strip() for p in _split_outside_parens(raw or "") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} & {parts[1]}"
    return f"{', '.join(parts[:-1])} & {parts[-1]}"

def _collapse_ws(s: str) -> str:
    """Collapse internal whitespace to single spaces; trim ends."""
    return " ".join((s or "").split())

def _pref(name: str, prefix: str = WIKI_PREFIX) -> str:
    """Prefix a page/redirect name with the LiT namespace."""
    return f"{prefix}{name}"

def _unit_count_from_desc(desc_fields: dict) -> int:
    """Return how many title units exist (based on titleN fields present)."""
    nums = []
    for k in desc_fields.keys():
        if k.startswith("title") and k[5:].isdigit():
            nums.append(int(k[5:]))
    return max(nums) if nums else 1

def _build_redirect_sources(desc_fields: dict, wiki_page_name: str) -> list[str]:
    """
    From parsed description, build redirect source names (UNPREFIXED).
    Rules:
      - For each unit i>=2: add Titlei; and Titlei: Subtitlei (if subtitle exists)
      - If unit1 has a subtitle: add 'Title1' (lazy search)
      - Drop anything equal (case-insensitive) to the final wiki_page_name
      - Collapse whitespace; preserve punctuation/diacritics
      - Case-insensitive de-duplication; preserve first-seen casing
    """
    sources: list[str] = []
    seen_ci: set[str] = set()

    def add(name: str):
        n = _collapse_ws(name)
        if not n:
            return
        if n.casefold() == (wiki_page_name or "").casefold():
            return
        ci = n.casefold()
        if ci not in seen_ci:
            seen_ci.add(ci)
            sources.append(n)

    n_units = _unit_count_from_desc(desc_fields)
    # Alt units
    for i in range(2, n_units + 1):
        ti = (desc_fields.get(f"title{i}") or "").strip()
        si = (desc_fields.get(f"subtitle{i}") or "").strip()
        if ti:
            add(ti)
            if si:
                add(f"{ti}: {si}")

    # Lazy form for unit1 if it has a subtitle
    t1 = (desc_fields.get("title1") or "").strip()
    s1 = (desc_fields.get("subtitle1") or "").strip()
    if t1 and s1:
        add(t1)

    return sources


def _raw_mame_title(minfo: dict, fallback: str) -> str:
    """Return the raw MAME title for a machine (no transformer overrides)."""
    return (minfo.get("description")
            or minfo.get("title")
            or minfo.get("fullname")
            or fallback)

def _mame_titles_for_parent(parent_name: str,
                            mame: Dict[str, Any],
                            parent_index: Dict[str, Any]) -> list[dict]:
    """
    Build the MAME titles list for a parent:
      [{"role": "parent"/"clone", "machine": shortname, "title": raw MAME title, "year": <as-is>}, ...]
    Parent row always comes first, followed by clones sorted by machine.
    """
    out: list[dict] = []

    # Parent row
    pinfo = mame.get(parent_name, {})
    out.append({
        "role": "parent",
        "machine": parent_name,
        "title": _raw_mame_title(pinfo, parent_name),
        "year": pinfo.get("year"),  # keep as-is, e.g. "198?" or "1980"
    })

    # Clone rows
    clones = sorted((parent_index.get("parents") or {}).get(parent_name, []) or [])
    for c in clones:
        cinfo = mame.get(c, {})
        out.append({
            "role": "clone",
            "machine": c,
            "title": _raw_mame_title(cinfo, c),
            "year": cinfo.get("year"),
        })

    return out

def _wiki_page_name_from_desc(desc_fields: dict) -> str:
    """Build the wiki page name as 'Title: Subtitle' (or just 'Title' if no subtitle)."""
    title = (desc_fields.get("title1") or "").strip()
    subtitle = (desc_fields.get("subtitle1") or "").strip()
    return f"{title}: {subtitle}" if subtitle else title


def _clone_entries_for_parent(parent_name: str,
                              mame: Dict[str, Any],
                              parent_index: Dict[str, Any]) -> list[dict]:
    """
    Build the clone list for a given parent:
      [{"machine": <shortname>, "title": <raw MAME title>, "year": <as-is>}, ...]
    Always returns a list (possibly empty).
    """
    clones = (parent_index.get("parents") or {}).get(parent_name, []) or []
    out: list[dict] = []
    for c in sorted(clones):  # stable order
        minfo = mame.get(c, {})
        out.append({
            "machine": c,
            "title": _raw_mame_title(minfo, c),   # raw MAME title, no overrides
            "year": minfo.get("year"),            # as-is, e.g. "198?" or "1980"
        })
    return out


def _core(s: str | None) -> str | None:
    """Extract numeric core like '0.279' or '2.79' from a version string."""
    if not s:
        return None
    m = _VERSION_CORE_RX.search(s)
    return m.group(0) if m else None


# ----------------------------
# IO helpers
# ----------------------------

def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to read {path}: {e}")
        return None


def _write_json(path: Path, obj: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        log.info(f"Wrote {path}")
        return True
    except Exception as e:
        log.error(f"Failed to write {path}: {e}")
        return False


# ----------------------------
# Classification helpers
# ----------------------------

def _classify(machine: str, ini_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Return normalised classification for a machine using the INI aggregation map.
    Missing/empty fields become 'unknown' (category becomes ['unknown']).
    """
    row = ini_map.get(machine)
    if not row:
        return {"game_status": "unknown", "category": ["unknown"], "type": "unknown"}
    gs = row.get("game_status", "unknown") or "unknown"
    cat = row.get("category")
    if not isinstance(cat, list) or not cat:
        cat = ["unknown"]
    typ = row.get("type", "unknown") or "unknown"
    return {"game_status": gs, "category": cat, "type": typ}


def _is_eligible_parent(machine: str,
                        mame: Dict[str, Any],
                        ini_map: Dict[str, Dict[str, Any]]) -> bool:
    """
    Eligibility predicate for parent machines:
      - must not be a clone,
      - INI says game_status == 'game',
      - INI category includes 'Arcade'.
    """
    info = mame.get(machine, {})
    if info.get("cloneof"):
        return False
    c = _classify(machine, ini_map)
    return (c["game_status"] == "game") and ("Arcade" in c["category"])


def _build_final_set(eligible_parents: Set[str],
                     parent_index: Dict[str, Any]) -> Set[str]:
    """
    Expand the eligible parent set with ALL their clones using mame_parent_index.json.
    """
    final: Set[str] = set(eligible_parents)
    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})
    for p in sorted(eligible_parents):
        final.update(parents_map.get(p, []))
    return final


def _machine_title(m: Dict[str, Any], fallback: str) -> str:
    """Get a display title for a MAME record with sensible fallbacks."""
    return m.get("description") or m.get("title") or m.get("fullname") or fallback


def _truthy_flag(v) -> bool:
    """
    Normalise a variety of MAME booleanish forms to True/False.
    Accepts booleans, numbers, and strings like 'yes'/'no', '1'/'0', etc.
    """
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "y", "t"}:
            return True
        if s in {"0", "false", "no", "n", "f", ""}:
            return False
    return False


def _load_title_overrides(path: Path) -> dict:
    """
    Load optional title overrides:
      {
        "machine_name": {
          "description": "<replacement text>",
          "apply_if_unbalanced": true|false,
          "note": "why"
        },
        ...
      }
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning(f"Failed to read title overrides {path}: {e}")
        return {}


def _dedupe_anomalies_preferring_pre_override(anoms: dict) -> dict:
    """
    De-duplicate anomaly examples by (machine, example),
    preferring entries tagged pre_override=True when both exist.
    """
    out = {}
    for cat, items in anoms.items():
        seen = {}
        for it in items:
            key = (it.get("machine"), it.get("example"))
            prev = seen.get(key)
            if prev is None:
                seen[key] = it
            else:
                if it.get("pre_override") and not prev.get("pre_override"):
                    seen[key] = it
        out[cat] = list(seen.values())
    return out


# ----------------------------
# TITLE PARSING (fixed)
# ----------------------------

def _normalise_inside_group(s: str) -> Tuple[str, bool]:
    """Inside a bracket group, replace top-level ' - ' and ' / ' with ', '."""
    changed = False
    out = []
    dR = dS = 0
    i = 0
    while i < len(s):
        if dR == 0 and dS == 0:
            if s.startswith(" - ", i):
                out.append(", "); changed = True; i += 3; continue
            if s.startswith(" / ", i):
                out.append(", "); changed = True; i += 3; continue
        ch = s[i]
        if ch == "(": dR += 1
        elif ch == ")": dR = max(0, dR - 1)
        elif ch == "[": dS += 1
        elif ch == "]": dS = max(0, dS - 1)
        out.append(ch); i += 1
    return ("".join(out), changed)


def _top_level_groups(unit: str) -> List[Tuple[int, int, str, str]]:
    """
    Return top-level bracket groups in this unit:
    list of (start, end, bracket_type, content_normalised).
    Nested groups are preserved INSIDE content, not yielded separately.
    """
    groups = []
    dR = dS = 0
    i = 0
    while i < len(unit):
        ch = unit[i]
        if ch in "([":
            if dR == 0 and dS == 0:  # top-level group starts here
                start = i
                btype = ch
                # scan to its matching close, allowing nesting
                i += 1
                dR += (ch == "(")
                dS += (ch == "[")
                while i < len(unit) and (dR > 0 or dS > 0):
                    if unit[i] == "(": dR += 1
                    elif unit[i] == ")": dR -= 1
                    elif unit[i] == "[": dS += 1
                    elif unit[i] == "]": dS -= 1
                    i += 1
                end = i - 1  # index of the closing ) or ]
                raw = unit[start+1:end]
                content, _ = _normalise_inside_group(raw)
                groups.append((start, end, "(" if btype == "(" else "[", content))
                continue
        # advance normally
        i += 1
    return groups


def _first_trailing_start(unit: str, groups: List[Tuple[int,int,str,str]]) -> Optional[int]:
    """
    Find the start index of the FIRST top-level group that is a 'trailing' group:
    i.e., preceded by whitespace (so not infix like APE(X)C).
    """
    for (start, end, _, _) in groups:
        if start == 0:
            return start
        prev = unit[start - 1]
        if prev.isspace():
            return start
    return None


def _split_outside_tokens_after(unit: str, groups: List[Tuple[int,int,str,str]], from_index: int) -> List[str]:
    """
    Collect outside (non-bracket) token fragments AFTER from_index,
    skipping over bracket groups. Clean leading/trailing punctuation.
    """
    tokens: List[str] = []
    spans = [(s, e) for (s, e, _, _) in groups if s >= from_index]
    spans.sort()
    cursor = from_index
    for (s, e) in spans:
        if s > cursor:
            frag = unit[cursor:s].strip()
            if frag:
                tokens.append(_clean_token(frag))
        cursor = e + 1
    if cursor < len(unit):
        frag = unit[cursor:].strip()
        if frag:
            tokens.append(_clean_token(frag))
    return [t for t in tokens if t]


def _clean_token(t: str) -> str:
    """Trim and drop leading/trailing punctuation commonly used as separators."""
    t = t.strip()
    while t and t[0] in "-:,/;()[]":
        t = t[1:].lstrip()
    while t and t[-1] in "-:,/;()[]":
        t = t[:-1].rstrip()
    t = " ".join(t.split())
    return t


def _find_infix_brackets_no_spaces(s: str) -> bool:
    """Heuristic: bracket group immediately between alnum on both sides."""
    return _INFIX_RE.search(s) is not None


def _find_unbalanced(full: str) -> Tuple[bool, bool]:
    """Return (unbalanced_round, unbalanced_square) for a full string."""
    dR = dS = 0
    for ch in full:
        if ch == "(": dR += 1
        elif ch == ")": dR -= 1
        elif ch == "[": dS += 1
        elif ch == "]": dS -= 1
    return (dR != 0, dS != 0)


def _parse_unit(unit_text: str) -> Tuple[str, str, List[str], List[str], Dict[str, bool]]:
    """
    Parse ONE title unit:
      returns (base_title, subtitle, group_contents_in_order, outside_tokens_after_first_group, warn_flags)
      - Only top-level groups are returned in 'group_contents_in_order' (nested are inside).
      - 'outside_tokens_after_first_group' are non-bracket text fragments after the first group.
    """
    warn = {"odd_separator_usage": False}
    groups = _top_level_groups(unit_text)
    first_tr_start = _first_trailing_start(unit_text, groups)
    cut = first_tr_start if first_tr_start is not None else len(unit_text)
    head = unit_text[:cut]

    # Subtitle split on first ' - ' or ':' outside brackets
    sub_pos = None
    chosen = None
    for sep in (" - ", ":"):
        idx = head.find(sep)
        if idx != -1 and (sub_pos is None or idx < sub_pos):
            sub_pos = idx
            chosen = sep
    if sub_pos is not None:
        base = head[:sub_pos].strip()
        subtitle = head[sub_pos + len(chosen):].strip()
    else:
        base = head.strip()
        subtitle = ""

    # Determine if we normalised anything in groups (for warnings)
    for (_, _, _, content_raw) in groups:
        _, changed = _normalise_inside_group(content_raw)
        if changed:
            warn["odd_separator_usage"] = True
            break

    outside_tokens: List[str] = []
    if first_tr_start is not None:
        outside_tokens = _split_outside_tokens_after(unit_text, groups, from_index=groups[0][1] + 1)

    group_contents = [g[3].strip() for g in groups]
    return base, subtitle, group_contents, outside_tokens, warn


def _parse_description(full_desc: str) -> Tuple[Dict[str, str], Dict[str, List[Dict[str, str]]]]:
    """
    Build numbered title/subtitle/version fields + single 'global_version'.
    Returns (description_dict, anomalies_dict).
    """
    anomalies: Dict[str, List[Dict[str, str]]] = {
        "unbalanced_round_brackets": [],
        "unbalanced_square_brackets": [],
        "infix_brackets_no_spaces": [],
        "ambiguous_trailing_tokens": [],
        "odd_separator_usage": [],
    }

    # Global anomaly checks on the raw string
    unb_round, unb_square = _find_unbalanced(full_desc)
    if unb_round:  anomalies["unbalanced_round_brackets"].append({"example": full_desc})
    if unb_square: anomalies["unbalanced_square_brackets"].append({"example": full_desc})
    if _find_infix_brackets_no_spaces(full_desc):
        anomalies["infix_brackets_no_spaces"].append({"example": full_desc})

    # Split into title units outside brackets
    def split_top_level(text: str, delim: str) -> List[str]:
        out, buf = [], []
        dR = dS = 0
        i, L, dlen = 0, len(text), len(delim)
        while i < L:
            if dR == 0 and dS == 0 and text.startswith(delim, i):
                out.append("".join(buf)); buf = []; i += dlen; continue
            ch = text[i]
            if ch == "(": dR += 1
            elif ch == ")": dR = max(0, dR - 1)
            elif ch == "[": dS += 1
            elif ch == "]": dS = max(0, dS - 1)
            buf.append(ch); i += 1
        out.append("".join(buf))
        return out

    units = split_top_level(full_desc, " / ")

    unit_info = []
    total_top_groups = 0
    for u in units:
        base, sub, group_contents, outside_tokens, warn = _parse_unit(u)
        unit_info.append((base, sub, group_contents, outside_tokens, warn))
        total_top_groups += len(group_contents)
        if warn.get("odd_separator_usage"):
            anomalies["odd_separator_usage"].append({"example": full_desc})
        if outside_tokens:
            anomalies["ambiguous_trailing_tokens"].append({"example": full_desc})

    # Build numbered fields placeholders
    desc: Dict[str, str] = {}
    for idx in range(len(unit_info)):
        desc[f"title{idx+1}"] = ""
        desc[f"subtitle{idx+1}"] = ""
        desc[f"version{idx+1}"] = ""

    for idx, (base, sub, _, _, _) in enumerate(unit_info, start=1):
        desc[f"title{idx}"] = base
        desc[f"subtitle{idx}"] = sub

    # Decide global_version vs per-title versionN
    global_parts: List[str] = []
    if total_top_groups == 1:
        for (_, _, groups, outs, _) in unit_info:
            if groups:
                global_parts.append(groups[0])
                for t in outs:
                    global_parts.append(t)
                break
    else:
        for idx, (_, _, groups, outs, _) in enumerate(unit_info, start=1):
            if groups:
                desc[f"version{idx}"] = groups[0]
                for extra in groups[1:]:
                    global_parts.append(extra)
            for t in outs:
                global_parts.append(t)

    desc["global_version"] = ", ".join(p for p in global_parts if p)
    return desc, anomalies


# ----------------------------
# Main transform
# ----------------------------

def run_transformer(data_dir: Path = DATA_DIR) -> bool:
    started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    t0 = time.perf_counter()

    # Safe default for header; will be populated from summaries below
    wiki_header_versions = {
        "mame_xml_version": "Unknown",
        "gaming_history_xml_version": "Unknown",
        "ini_versions": {}
    }

    # Optional overrides
    overrides_path = DATA_DIR / "title_overrides.json"
    overrides = _load_title_overrides(overrides_path)
    have_overrides = isinstance(overrides, dict) and bool(overrides)

    overrides_applied: list[dict[str, str]] = []
    overrides_stats = {
        "configured": len(overrides),
        "eligible": 0,
        "applied": 0
    }

    # Load required inputs
    mame = _read_json(MAME_MACHINES_PATH)
    ini_map = _read_json(INI_CLASS_PATH)
    parent_index = _read_json(PARENT_INDEX_PATH)
    if not isinstance(mame, dict) or not isinstance(ini_map, dict) or not isinstance(parent_index, dict):
        log.error("Missing or invalid inputs; aborting transform.")
        return False

    # --- Read stage summaries (sources of truth for versions) ---
    mame_sum = _read_json(DATA_DIR / "mame_parsing_summary.json") or {}
    hist_sum = _read_json(DATA_DIR / "history_parsing_summary.json") or {}
    ini_sum  = _read_json(DATA_DIR / "ini_parsing_summary.json") or {}

    # Raw versions for the transform summary (audit only)
    versions = {
        "mame_build":      (mame_sum.get("mame")    or {}).get("build"),
        "history_version":  (hist_sum.get("history") or {}).get("version"),
        "history_date":     (hist_sum.get("history") or {}).get("date"),
        "ini_generated_at": (ini_sum.get("ini")      or {}).get("generated_at"),
    }

    # --- Build wiki header versions using creators' schemes (no mismatch reporting here) ---
    mame_build_raw   = (mame_sum.get("mame")    or {}).get("build")    # e.g. "0.279 (mame0279)"
    mame_core        = _core(mame_build_raw)                           # -> "0.279" or None
    hist_version_raw = (hist_sum.get("history") or {}).get("version")  # e.g. "2.79" / "2.79a"

    # Per-INI versions: tolerate current and older shapes
    ini_versions_raw: dict[str, str] = {}

    # Your current shape: { "ini": { "files": { "game_status": {...}, "category": {...}, "type": {...} } } }
    ini_root = (ini_sum.get("ini") or {}) if isinstance(ini_sum, dict) else {}
    files_node = ini_root.get("files")

    if isinstance(files_node, dict):
        for item in files_node.values():
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                ini_versions_raw[fn] = ver

    # Fallbacks for older/alternative shapes
    if not ini_versions_raw:
        # shape: { "files": [ {...}, {...} ] }
        files_list = ini_sum.get("files")
        if isinstance(files_list, list):
            for item in files_list:
                fn = (item.get("filename") or item.get("path") or "").strip()
                v  = item.get("version") or {}
                ver = v.get("mame_version") or v.get("raw") or "Unknown"
                if fn:
                    ini_versions_raw[fn] = ver

    if not ini_versions_raw:
        # stage-style: { "inputs": [ {...}, ... ] }
        for item in (ini_root.get("inputs") or ini_sum.get("inputs") or []):
            fn = (item.get("filename") or item.get("path") or "").strip()
            v  = item.get("version") or {}
            ver = v.get("mame_version") or v.get("raw") or "Unknown"
            if fn:
                ini_versions_raw[fn] = ver

    # Now build the header block
    wiki_header_versions = {
        "mame_xml_version":            mame_core or "Unknown",
        "gaming_history_xml_version":  hist_version_raw or "Unknown",  # keep GH style (e.g. "2.79a")
        "ini_versions":                {fn: (ini_versions_raw.get(fn) or "Unknown") for fn in ini_versions_raw}
    }


    # ---------------- Selection + Title parsing ----------------
    all_names = sorted(mame.keys())
    eligible_parents: Set[str] = {n for n in all_names if _is_eligible_parent(n, mame, ini_map)}
    included_parents: Set[str] = eligible_parents     # parents-only export

    out_map: Dict[str, Dict[str, Any]] = {}

    # Parent exclusion reasons (for info)
    excluded_reasons = {"not_game": 0, "not_arcade": 0, "unknown_classification": 0}

    # Flag tallies (now count PARENTS only)
    included_flags = {"isbios": 0, "isdevice": 0, "ismechanical": 0}

    # Track oddities while building records (e.g. parent listed in index but missing in mame map)
    missing_in_mame: List[str] = []

    # Title anomaly buckets (parents only, uncapped examples)
    title_anomalies: Dict[str, List[Dict[str, str]]] = {
        "unbalanced_round_brackets": [],
        "unbalanced_square_brackets": [],
        "infix_brackets_no_spaces": [],
        "ambiguous_trailing_tokens": [],
        "odd_separator_usage": [],
    }


    # --- Media label counters (parents only) ---
    media_label_counts: dict[str, int] = {}
    parents_with_any_media = 0

    # --- Audit: raw device strings we ignored (no known media mapping) ---
    ignored_device_counts: dict[str, int] = {}
    _IGNORED_TOP_N = 25  # change if you want more/less in the summary


    for name in sorted(included_parents):
        minfo = mame.get(name)
        if not minfo:
            continue  # defensive

        cls = _classify(name, ini_map)

        # Pre-override anomaly capture on ORIGINAL raw MAME title
        raw_desc_original = _machine_title(minfo, name)
        _, pre_anoms = _parse_description(raw_desc_original)
        for k, lst in pre_anoms.items():
            for item in lst:
                item["machine"] = name
                item["pre_override"] = True
            title_anomalies[k].extend(lst)

        # Optional override for parents only
        orig_unbalanced_round, orig_unbalanced_square = _find_unbalanced(raw_desc_original)
        ov = overrides.get(name)
        raw_desc = raw_desc_original
        if ov and isinstance(ov, dict):
            apply_if_unbalanced = bool(ov.get("apply_if_unbalanced", True))
            condition_met = (not apply_if_unbalanced) or orig_unbalanced_round or orig_unbalanced_square
            if condition_met:
                overrides_stats["eligible"] += 1
                new_desc = ov.get("description")
                if isinstance(new_desc, str) and new_desc.strip():
                    raw_desc = new_desc.strip()
                    overrides_applied.append({
                        "machine": name,
                        "from": raw_desc_original,
                        "to": raw_desc,
                        "reason": ov.get("note", "override")
                    })
                    overrides_stats["applied"] += 1

        # Parse (possibly overridden) title for wiki_page_name + keep parsed fields for reference
        desc_fields, _ = _parse_description(raw_desc)
        wiki_page_name = _wiki_page_name_from_desc(desc_fields)

        #raw_man = minfo.get("manufacturer")
        #manufacturer_display = format_manufacturers_for_wiki(raw_man)
        raw_man = minfo.get("manufacturer") or ""
        manufacturer_display = join_with_ampersand(_split_outside_parens(raw_man))

        # ROM summary (data already parsed upstream)
        rom_count       = int(minfo.get("rom_count") or 0)
        rom_bytes_total = int(minfo.get("rom_bytes_total") or 0)
        disk_required = minfo.get("disk_required")  # "yes" / "no"
        disk_regions  = minfo.get("disk_regions")   # list (per your schema)

        # Media label counting (parents only)
        if (str(disk_required or "").lower() == "yes"):
            labels_for_counts = _normalise_device_list_to_media(disk_regions)
            if labels_for_counts:
                parents_with_any_media += 1
                for lab in dict.fromkeys(labels_for_counts):  # de-dupe per parent
                    media_label_counts[lab] = media_label_counts.get(lab, 0) + 1
            else:
                log.debug(f"[transformer::run_transformer] No media mapped for {name}; disk_regions={disk_regions!r}")


            # Audit: record any raw entries that didn't map to a known medium
            seq = disk_regions if isinstance(disk_regions, (list, tuple)) else ([disk_regions] if disk_regions else [])
            for raw in seq:
                if _normalise_device_to_media(str(raw)) is None:
                    ignored_device_counts[str(raw)] = ignored_device_counts.get(str(raw), 0) + 1
                    
        # Normalise raw device names to display media labels
        roms_display = _format_rom_block(rom_count, rom_bytes_total, disk_required, disk_regions)


        record = {
            "wiki_page_name": wiki_page_name,
            "description": desc_fields,  # retained for QA/reference
            "year": minfo.get("year") if minfo.get("year") not in ("", None) else None,
            "manufacturer": manufacturer_display if manufacturer_display else None,
            "roms_display": roms_display,  # e.g. "10 ROMs\n25,376 bytes (24.78 KiB)\nPlus: laserdisc"

            # Classifications (from INI)
            "game_status": cls["game_status"],
            "category": cls["category"],
            "type": cls["type"],

            # MAME flags (report-only)
            "isbios": _truthy_flag(minfo.get("isbios")),
            "isdevice": _truthy_flag(minfo.get("isdevice")),
            "ismechanical": _truthy_flag(minfo.get("ismechanical")),
            "requires_samples": _truthy_flag(minfo.get("requires_samples")),

            # NEW: preformatted titles table rows for wiki (parent first, then clones by machine)
            "mame_titles": _mame_titles_for_parent(name, mame, parent_index),
        }

        # If you still tally flags, this now counts parents only
        if _truthy_flag(minfo.get("isbios")):       included_flags["isbios"] += 1
        if _truthy_flag(minfo.get("isdevice")):     included_flags["isdevice"] += 1
        if _truthy_flag(minfo.get("ismechanical")): included_flags["ismechanical"] += 1

        out_map[name] = record

    # --- Write wiki output (header + games) ---
    wiki_doc = {
        "header": {
            "versions": wiki_header_versions,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "wiki_schema": WIKI_SCHEMA,
        },
        "games": out_map
    }
    ok_out = _write_json(WIKI_OUT_PATH, wiki_doc)

    # --- Build and write transform summary ---
    parents_total = sum(1 for v in mame.values() if not v.get("cloneof"))
    clones_total  = sum(1 for v in mame.values() if v.get("cloneof"))


    # ---------------- Wiki pages & redirects (parents only) ----------------
    # Build (page_name, machine) pairs first so we can sort by page title
    pairs: list[tuple[str, str]] = [(_pref(rec.get("wiki_page_name") or ""), machine)
                                    for machine, rec in out_map.items()]

    # Sort by page title (case-insensitive)
    pairs.sort(key=lambda t: t[0].casefold())

    # Reconstruct pages_map in sorted order (machine -> prefixed page)
    pages_map: dict[str, str] = {machine: page for page, machine in pairs}

    # Group by page to build page_names list and detect collisions (do this ONCE)
    page_to_machines: dict[str, list[str]] = {}
    for page, machine in pairs:
        page_to_machines.setdefault(page, []).append(machine)

    # Already sorted by page via 'pairs'; preserve that order
    page_names_list: list[str] = list(page_to_machines.keys())

    # Collisions: same page name claimed by >1 parent
    page_name_collisions: list[dict] = [
        {"page": page, "machines": sorted(machines)}
        for page, machines in page_to_machines.items()
        if len(machines) > 1
    ]

    # Build redirects (from parent parsed titles only; no clones)
    # Case-insensitive de-duplication on sources; record conflicts if the same source maps to different targets
    redirects_map: dict[str, str] = {}
    redirect_conflicts: list[dict] = []
    sources_seen: dict[str, str] = {}  # lower(source) -> target

    for machine, rec in out_map.items():
        target = pages_map[machine]  # prefixed page name
        desc   = rec.get("description") or {}
        wiki_name = rec.get("wiki_page_name") or ""
        for src in _build_redirect_sources(desc, wiki_name):
            psrc = _pref(src)
            key = psrc.casefold()
            prev = sources_seen.get(key)
            if prev is None:
                sources_seen[key] = target
                redirects_map[psrc] = target
            elif prev != target:
                owners = [m for m, p in pages_map.items() if p in {prev, target}]
                redirect_conflicts.append({
                    "source": psrc,
                    "targets": sorted({prev, target}),
                    "machines": sorted(set(owners)),
                })

    # Optional: sort redirects for stability BEFORE embedding
    redirects_map = dict(sorted(redirects_map.items(), key=lambda kv: kv[0].casefold()))

    # Assemble and write file (stats near the top)
    wiki_pages_redirects = {
        "schema_version": 1,
        "prefix": WIKI_PREFIX,
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "stats": {
            "parents_total": len(out_map),
            "page_names_total": len(page_names_list),
            "redirects_total": len(redirects_map),
            "page_name_collisions": len(page_name_collisions),
            "redirect_conflicts": len(redirect_conflicts),
        },
        "pages": pages_map,              # machine -> page (sorted by page)
        "page_names": page_names_list,   # sorted list of pages
        "redirects": redirects_map,      # source -> target (both prefixed)
        "conflicts": {
            "page_name_collisions": page_name_collisions,
            "redirect_conflicts": redirect_conflicts,
        },
    }

    _write_json(WIKI_PAGES_REDIRECTS_PATH, wiki_pages_redirects)


    finished_utc = datetime.datetime.utcnow().isoformat() + "Z"
    duration = round(time.perf_counter() - t0, 3)

    # Inputs (artefacts the transformer READ)
    inputs_map = {
        "mame_machines":       str(MAME_MACHINES_PATH).replace("\\", "/"),
        "ini_classifications": str(INI_CLASS_PATH).replace("\\", "/"),
        "mame_parent_index":   str(PARENT_INDEX_PATH).replace("\\", "/"),
    }
    if have_overrides:
        inputs_map["title_overrides"] = str(overrides_path).replace("\\", "/")

    # Outputs (artefacts the transformer WROTE)
    outputs_map = {
        "exotica_lit_wiki":            str(WIKI_OUT_PATH).replace("\\", "/"),
        "wiki_pages_and_redirects":    str(WIKI_PAGES_REDIRECTS_PATH).replace("\\", "/"),
    }

    #parents_with_clones = sum(1 for r in out_map.values() if r["clones"])
    parents_with_clones = sum(
        1 for r in out_map.values()
        if any(t.get("role") == "clone" for t in r.get("mame_titles", []))
    )
    
    #total_clones_linked = sum(len(r["clones"]) for r in out_map.values())
    total_clones_linked = sum(
        sum(1 for t in r.get("mame_titles", []) if t.get("role") == "clone")
        for r in out_map.values()
    )
        
    # De-dupe anomalies (prefer pre_override entries) and count
    title_anomalies = _dedupe_anomalies_preferring_pre_override(title_anomalies)
    title_anomaly_counts = {k: len(v) for k, v in title_anomalies.items()}

    # Sort media labels for stability (already present)
    media_label_counts_sorted = dict(sorted(media_label_counts.items(), key=lambda kv: kv[0].casefold()))

    # Top-N ignored raw device strings by frequency (desc), then name (asc)
    ignored_sorted = sorted(ignored_device_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ignored_top = [{"device": k, "count": v} for k, v in ignored_sorted[:_IGNORED_TOP_N]]
    ignored_total = sum(ignored_device_counts.values())


    summary = {
        "transformer_schema": TRANSFORMER_SCHEMA,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "duration_seconds": duration,
        "inputs": inputs_map,
        "outputs": outputs_map,
        "versions": versions,
        "counts": {
            "mame_total": len(mame),
            "parents_total": parents_total,
            "clones_total": clones_total,
            "eligible_parents": len(eligible_parents),
            "final_included": len(out_map),
            "parents_with_clones": parents_with_clones,
            "total_clones_linked": total_clones_linked,
            "parents_without_clones": len(eligible_parents)-parents_with_clones,
            "parents_with_any_media": parents_with_any_media,
            #"media_label_counts": dict(sorted(media_label_counts.items(), key=lambda kv: kv[0].casefold())),
            #"media_label_counts": dict(
            #    sorted(media_label_counts.items(), key=lambda kv: kv[0].casefold())
            #),            
            "media_label_counts": media_label_counts_sorted,

        },
        "excluded_parents_by_reason": excluded_reasons,
        "included_flags": included_flags,
        "title_anomaly_counts": title_anomaly_counts,
        "title_anomalies": title_anomalies,
        "title_overrides": {
            "stats": overrides_stats,
            "applied": overrides_applied
        },
        "notes": {
            "ports_attached": False,
            "filter_rules": {
                "game_status_equals": "game",
                "category_must_include": "Arcade",
                "ignore_coin_op_games": True,
                "ignore_type_for_filter": True,
                "ignore_isbios_isdevice_ismechanical_for_filter": True
            },
            "title_parsing": {
                "numbered_fields": True,
                "global_version_is_single_string": True,
                "only_top_level_groups": True,
                "nested_preserved_inside": True
            },
            "clones_list_title_source": "raw MAME 'description' (no overrides)",
            "ignored_media_devices": {
                "total_ignored_entries": ignored_total,          # sum of all unmapped raw entries
                "unique_ignored": len(ignored_device_counts),    # how many distinct raw strings
                "top_ignored": ignored_top,                      # top N offenders
            },                        
        },
        "errors": [] if ok_out and not missing_in_mame else (
            [{"missing_in_mame": missing_in_mame}] if missing_in_mame else []
        ),
    }

    orphans = [k for k, v in out_map.items() if "mame_titles" not in v]
    if orphans:
        log.warning(f"{len(orphans)} parents missing mame_titles (first few: {orphans[:5]})")

    if ignored_top:
        log.info(f"Top ignored media devices: {ignored_top[:5]}")

    ok_sum = _write_json(TRANS_SUMMARY_PATH, summary)
    log.info(f"Transformer completed in {duration:.2f}s "
             f"(eligible_parents={len(eligible_parents)}, included={len(out_map)})")
    return bool(ok_out and ok_sum)


if __name__ == "__main__":
    ok = run_transformer(DATA_DIR)
    raise SystemExit(0 if ok else 1)
