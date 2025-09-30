"""
Filename: transformer.py
Version: 1.0.1
Last modified: 2025-09-12
Author: Jason (XtC) Skelly (Open University TM470, 2025)

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Transforms parsed artefacts into a Wiki-ready dataset in a single step.

Scope:
- Select parent machines where INI says game_status == "game" AND category includes "Arcade".
- Include a parent in the final export only if the parent OR any of its clones has ≥1 valid
  Gaming-History port row (platform present). Clone data is used for ports and titles display,
  but the export is parent-centric.
- Parse titles into numbered fields (titleN / subtitleN / versionN) plus a global_version string.
  Title parsing tolerates nested brackets and reports anomalies for QA.
- Build wiki display blocks for ROM/media, chips/audio, displays and controls.
- Attach cleaned “ports_display” per category (parent+clone rows combined with date sorting).
- Generate a deterministic pages/redirects map for the ExoticA namespace.

Inputs:
- output/mame_machines.json
- output/gh_ini_classifications.json
- output/mame_parent_index.json
- data/history_parsing_summary.json            (for version header)
- data/mame_parsing_summary.json               (for version header)
- data/ini_parsing_summary.json                (for INI version header)
- data/title_overrides.json (optional)

Outputs:
- output/exotica_lit_wiki.json                 (Wiki-ready projection)
- output/exotica_lit_raw_data.json             (Rich, review-oriented projection)
- output/exotica_wiki_pages_and_redirects.json (Deterministic list + redirects map)
- data/transform_summary.json                  (counts, QA diagnostics, and notes)

Returns:
- True on success, False otherwise.

Notes:
- Deterministic ordering is preserved throughout for stable diffs.
- Ports are attached (parent and clone provenance retained for audit).
- See transform_summary.json → "notes" for the exact selection and parsing rules.
This file is part of a student project and is not intended for commercial use.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Set, List, Tuple, Sequence, Iterable
import json
import datetime
import time
import re
from collections import Counter

from mht.utils.config import LOG_LEVEL
from mht.utils.logger import setup_logger, debug_log
from mht.utils.versions import SCHEMA_IDS, schema_version, tool_version, output_schema
from mht.utils.stamps import make_stamp, load_stamp, save_stamp, is_fresh

log = setup_logger(log_level=LOG_LEVEL)

# Legacy field to keep for one cycle, but derive from the canonical summary schema now:
TRANSFORMER_SCHEMA = schema_version(SCHEMA_IDS["transform"])  # was "0.8"

# Output dataset schemas (IDs + versions) now from one source of truth:
SCHEMA_ID_WIKI  = output_schema("wiki")["id"]
SCHEMA_VER_WIKI = output_schema("wiki")["version"]

SCHEMA_ID_RAW   = output_schema("raw")["id"]
SCHEMA_VER_RAW  = output_schema("raw")["version"]

SCHEMA_ID_PAGES  = output_schema("pages")["id"]
SCHEMA_VER_PAGES = output_schema("pages")["version"]

DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")
WIKI_PREFIX = "Lost In Translation/"

#--- Input ---
MAME_MACHINES_PATH   = OUTPUT_DIR / "mame_machines.json"
INI_CLASS_PATH       = OUTPUT_DIR / "gh_ini_classifications.json"
PARENT_INDEX_PATH    = OUTPUT_DIR / "mame_parent_index.json"
GH_SYSTEM_PORTS_PATH = OUTPUT_DIR / "gh_system_ports.json"

#--- Output ---
WIKI_OUT_PATH             = OUTPUT_DIR / "exotica_lit_wiki.json"
RAW_OUT_PATH              = OUTPUT_DIR / "exotica_lit_raw_data.json"
TRANS_SUMMARY_PATH        = DATA_DIR / "transform_summary.json"
WIKI_PAGES_REDIRECTS_PATH = OUTPUT_DIR / "exotica_wiki_pages_and_redirects.json"

_ALNUM = re.compile(r"[A-Za-z0-9]")
_INFIX_RE = re.compile(r"[A-Za-z0-9]\([^()\[\]]+\)[A-Za-z0-9]")
_VERSION_CORE_RX = re.compile(r"\d+(?:\.\d+)+")

# Display precedence for the media "Plus:" line (higher = earlier).
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

_CONTROL_TYPE_LABELS = {
    "joy": "Joystick",
    "doublejoy": "Dual Joystick",
    "triplejoy": "Triple Joystick",
    "stick": "Analogue Joystick",
    "only_buttons": "Buttons Only",
    "paddle": "Paddle",
    "dial": "Dial",
    "trackball": "Trackball",
    "mouse": "Mouse",
    "positional": "Positional",
    "lightgun": "Light Gun",
    "pedal": "Pedal",
    "keyboard": "Keyboard",
    "keypad": "Keypad",
    "mahjong": "Mahjong Panel",
    "hanafuda": "Hanafuda Panel",
    "gambling": "Gambling Panel",
    # fallback → title-case of raw type
}

_TERMINAL_PUNCT = ('.', '!', '?', '…')

def _dedupe_ci_preserve_order(items: list[str]) -> list[str]:
    """Case-insensitive de-duplication preserving first-seen casing and order."""
    out, seen = [], set()
    for s in items or []:
        key = (s or "").casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _primary_redirects_for_unit1(desc_fields: dict, target_page_name: str) -> list[str]:
    """
    Build redirects for unit 1 only:
      - If Subtitle1 present: ["Title1: Subtitle1", "Title1"]
      - Else: ["Title1"]
    Exclude any equal (case-insensitive) to target_page_name.
    Collapse internal whitespace like _collapse_ws.
    """
    t = _collapse_ws((desc_fields.get("title1") or "").strip())
    s = _collapse_ws((desc_fields.get("subtitle1") or "").strip())
    target_ci = (target_page_name or "").casefold()
    out: list[str] = []
    if not t:
        return out
    if s:
        full = _collapse_ws(f"{t}: {s}")
        if full.casefold() != target_ci:
            out.append(full)
        if t.casefold() != target_ci:
            out.append(t)
    else:
        if t.casefold() != target_ci:
            out.append(t)
    return _dedupe_ci_preserve_order(out)


def _clone_primary_redirects(clone_machine: str,
                             mame: Dict[str, Any],
                             target_page_name: str) -> list[str]:
    """
    Parse the clone's raw MAME title and return unit-1 redirects
    (full 'Title: Subtitle' + lazy 'Title' when Subtitle exists; else just 'Title').
    No versions/global_version are used. Results are unprefixed.
    """
    minfo = mame.get(clone_machine) or {}
    raw = _raw_mame_title(minfo, clone_machine)
    desc_fields, _ = _parse_description(raw)
    return _primary_redirects_for_unit1(desc_fields, target_page_name)


def _gh_ids_from_ports_obj(ports_obj: dict) -> list[int]:
    """
    Flatten and de-duplicate GH ids found in a ports object.
    Returns a stable, ascending list of integers.
    """
    ids: set[int] = set()
    if not isinstance(ports_obj, dict):
        return []
    p = ports_obj.get("parent_source") or {}
    gid = p.get("gh_id")
    if isinstance(gid, int):
        ids.add(gid)
    for cs in (ports_obj.get("clone_sources") or []):
        gid = (cs or {}).get("gh_id")
        if isinstance(gid, int):
            ids.add(gid)
    return sorted(ids)

def _collect_gh_ids_from_ports(ports_obj: dict) -> list:
    """
    Return a stable, de-duplicated list of Gaming-History IDs present in a ports object.

    This scans both the parent_source and all clone_sources. Null/missing IDs are ignored.
    The result is sorted by string representation for deterministic output across runs,
    while preserving original types (e.g., ints remain ints).

    Args:
        ports_obj (dict): The ports structure built by _build_ports_for_parent().

    Returns:
        list: Sorted unique GH IDs (e.g., [123, 456]) found anywhere in ports_obj.
    """
    if not isinstance(ports_obj, dict):
        return []

    ids = set()

    # parent
    p = ports_obj.get("parent_source")
    if isinstance(p, dict):
        gid = p.get("gh_id")
        if gid is not None:
            ids.add(gid)

    # clones
    for c in (ports_obj.get("clone_sources") or []):
        if not isinstance(c, dict):
            continue
        gid = c.get("gh_id")
        if gid is not None:
            ids.add(gid)

    # Sort deterministically but keep original types
    return sorted(ids, key=lambda x: str(x))

def _render_chips_display(
    chips_raw: dict,
    requires_samples: bool = False,
    sound_channels: int | None = None,
    speaker_count: int | None = None,
) -> dict[str, list[str]]:
    """
    Build wiki-friendly chip lines for CPUs and Audio Chips.
    Accepts either:
      - dict sections with .get('items'), or
      - plain lists of rows.
    Skips 'Speaker'/'Samples' in the audio chip list; appends tail lines under Audio Chips.
    """

    def _rows(section):
        """Return a list of rows from a section that may be a dict-with-items or a list."""
        if isinstance(section, dict):
            return section.get("items") or []
        return section or []

    def _norm_rows(rows):
        """Yield normalised dict rows: {'name': str, 'clock_hz': float|int|None} from dicts or strings."""
        for r in rows or []:
            if isinstance(r, dict):
                name = (r.get("name") or "").strip()
                clk  = r.get("clock_hz")
            elif isinstance(r, str):
                name = r.strip()
                clk  = None
            else:
                continue
            if name:
                yield {"name": name, "clock_hz": clk}

    def group_and_render(rows: list[dict]) -> list[str]:
        """
        Collapse identical chips by (name, rounded clock) and render human-readable lines.

        Expects rows like {'name': str, 'clock_hz': int|float|None}. Buckets by
        (name, round(clock_hz)), counts multiplicity, formats the clock using
        _hz_to_human()/_format_hz_3dp(), and returns labels such as
        "Yamaha YM2151 @ 3.580 MHz" or "(2x) OKI MSM6295". Ordering is
        case-insensitive by name, then by descending clock.
        """
        buckets: dict[tuple[str, int | None], int] = {}
        clocks: dict[tuple[str, int | None], float | None] = {}
        for r in rows:
            name = r["name"]
            clk  = r.get("clock_hz")
            bucket = round(float(clk)) if isinstance(clk, (int, float)) else None
            key = (name, bucket)
            buckets[key] = buckets.get(key, 0) + 1
            clocks.setdefault(key, float(clk) if isinstance(clk, (int, float)) else None)

        ordered = sorted(buckets.items(), key=lambda kv: (kv[0][0].casefold(), -(clocks[kv[0]] or -1)))

        lines: list[str] = []
        for (name, _bucket), count in ordered:
            clk_val = clocks[(name, _bucket)]
            if clk_val is not None:
                human = _hz_to_human(clk_val)
                if human:
                    val, unit = human
                    freq = f"{val:.3f} {unit}"
                else:
                    freq = _format_hz_3dp(clk_val) or ""
            else:
                freq = ""
            base = name + (f" @ {freq}" if freq else "")
            lines.append(f"({count}x) {base}" if count > 1 else base)
        return lines

    # ---- normalise sources ----
    cpus_src_rows       = _rows((chips_raw or {}).get("cpus"))
    audio_src_rows_all  = _rows((chips_raw or {}).get("audio_chips"))

    cpus_src      = list(_norm_rows(cpus_src_rows))
    audio_src_all = list(_norm_rows(audio_src_rows_all))

    # Exclude Speaker/Samples from the audio chip list itself
    audio_src = [r for r in audio_src_all if r["name"].lower() not in {"speaker", "samples"}]

    out = {
        "cpus": group_and_render(cpus_src),
        "audio_chips": group_and_render(audio_src),
    }

    # ---- tail lines under Audio Chips ----
    tail: list[str] = []
    if requires_samples:
        tail.append("Requires additional samples")

    if sound_channels is not None:
        try:
            n = int(sound_channels)
        except Exception:
            n = 0
        tail.append(f"Audio {'Channel' if n == 1 else 'Channels'}: {n}")

    if speaker_count is None:
        speaker_count = sum(1 for r in audio_src_all if r["name"].lower() == "speaker")
    try:
        nsp = int(speaker_count or 0)
    except Exception:
        nsp = 0
    tail.append(f"{'Speaker' if nsp == 1 else 'Speakers'}: {nsp}")

    if tail:
        out["audio_chips"].extend(tail)

    return out

def _render_mame_titles_display(rows: list[dict]) -> list[str]:
    """
    Render MAME parent+clone titles as single lines for the wiki:
      'Title (YYYY) [parent: machine]' / 'Title [clone: machine]' if year missing.
    Parent appears first; clones are ordered A→Z by 'title'.
    """
    if not isinstance(rows, list):
        return []

    # Split parent vs clones
    parent_rows = [r for r in rows if str(r.get("role", "")).strip().lower() == "parent"]
    clone_rows  = [r for r in rows if str(r.get("role", "")).strip().lower() != "parent"]

    # Sort clones by title (case-insensitive), stable tiebreak on machine
    clone_rows.sort(key=lambda r: (
        (r.get("title") or "").casefold(),
        (r.get("machine") or "").casefold()
    ))

    ordered = parent_rows + clone_rows

    out: list[str] = []
    for r in ordered:
        title   = (r.get("title") or "").strip()
        year    = (r.get("year") or "")
        role    = str(r.get("role", "parent")).strip().lower() or "parent"
        machine = (r.get("machine") or "").strip()

        if not title:
            continue  # defensive

        parts = [title]
        if str(year).strip():
            parts.append(f"({year})")

        # Include machine name in trailing tag
        if machine:
            parts.append(f"[{role}: {machine}]")
        else:
            parts.append(f"[{role}]")

        out.append(" ".join(parts))

    return out

def _canonical_port_key(row: dict) -> tuple:
    """
    Build a key that ignores provenance and formatting differences,
    so we can detect identical ports across parent/clone.
    """
    regions = tuple(r.strip() for r in (row.get("regions") or []) if isinstance(r, str))
    platform = (row.get("platform") or "").strip()
    title    = (row.get("title") or "").strip()
    date     = (row.get("date") or "").strip()
    publisher= (row.get("publisher") or "").strip()
    tags     = tuple(t.strip() for t in (row.get("additional_tags") or []) if isinstance(t, str))
    models   = tuple(m.strip() for m in (row.get("model") or []) if isinstance(m, str))
    comment  = (row.get("comment") or "").strip()
    # machine is deliberately excluded — that’s the provenance we’re checking across
    return (regions, platform, title, date, publisher, tags, models, comment)

def _has_parent_clone_duplicate_ports(ports_obj: dict) -> bool:
    """
    Return True if any category contains at least one identical port
    present in BOTH parent_source and ANY clone_source.
    """
    if not isinstance(ports_obj, dict):
        return False

    p = (ports_obj.get("parent_source") or {}).get("categories") or {}
    clones = [ (cs or {}).get("categories") or {} for cs in (ports_obj.get("clone_sources") or []) ]

    if not p or not clones:
        return False

    # Build per-category sets for the parent
    parent_sets: dict[str, set] = {}
    for cat, rows in p.items():
        s = set()
        for r in (rows or []):
            s.add(_canonical_port_key(r))
        if s:
            parent_sets[cat] = s

    if not parent_sets:
        return False

    # Check intersection with each clone per category
    for cdict in clones:
        for cat, rows in cdict.items():
            if cat not in parent_sets:
                continue
            for r in (rows or []):
                if _canonical_port_key(r) in parent_sets[cat]:
                    return True
    return False

def _date_sort_key(date_str: str, original_index: int) -> tuple[int, int, int, int]:
    """
    Turn a GH-cleaned partial date 'YYYY-MM-DD' (with possible 'X' chars) into a sortable key.
    Rules:
      - Replace 'X' with '0' to floor unknown components (earliest possible date).
      - Missing/empty handled by caller (we only call this for dated rows).
      - Use original_index as a final tiebreaker for stability.
    """
    s = (date_str or "").strip()
    y, m, d = "0000", "00", "00"
    parts = s.split("-")
    if len(parts) >= 1 and parts[0]:
        y = parts[0].replace("X", "0")
    if len(parts) >= 2 and parts[1]:
        m = parts[1].replace("X", "0")
    if len(parts) >= 3 and parts[2]:
        d = parts[2].replace("X", "0")
    try:
        yi = int(y)
    except ValueError:
        yi = 0
    try:
        mi = int(m)
    except ValueError:
        mi = 0
    try:
        di = int(d)
    except ValueError:
        di = 0
    return (yi, mi, di, original_index)

def _format_models_bracketed(models: list[str] | None) -> str:
    """Return '[A, B]' or '' (no leading space)."""
    models = [m.strip() for m in (models or []) if isinstance(m, str) and m.strip()]
    return f"[{', '.join(models)}]" if models else ""

def _title_case_words(s: str) -> str:
    """Return the string in title case (first letter upper, rest lower) per word."""
    return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in (s or "").split())

def _format_regions(regs: list[str] | None) -> str:
    """Format region codes as '[XX]' blocks concatenated without spaces, defaulting to '[??]'."""
    regs = regs or ["??"]
    regs = [r.strip() for r in regs if isinstance(r, str) and r.strip()]
    regs = regs or ["??"]
    return "".join(f"[{r}]" for r in regs)

def _format_additional_tags(tags: list[str] | None) -> str:
    """Format additional_tags as ' [A, B]' suffix or '' if none."""
    tags = [t.strip() for t in (tags or []) if isinstance(t, str) and t.strip()]
    return f" [{', '.join(tags)}]" if tags else ""

def _format_models(models: list[str] | None) -> str:
    """Format model list as ' [A, B]' suffix or '' if none."""    
    models = [m.strip() for m in (models or []) if isinstance(m, str) and m.strip()]
    return f" [{', '.join(models)}]" if models else ""

def _append_provenance_comment(existing: str | None, is_parent_row: bool, machine: str) -> str:
    """Append a provenance sentence noting whether the GH row came from the parent or a clone machine."""    
    role = "parent" if is_parent_row else "clone"
    prov = f"This GH port entry is based on the MAME {role} {machine}."
    c = (existing or "").strip()
    if c:
        if c.endswith(_TERMINAL_PUNCT):
            return f"{c} {prov}"
        else:
            return f"{c}. {prov}"
    else:
        return prov  # caller will add the leading ' : ' separator


def _render_ports_display(parent_machine: str, ports_obj: dict) -> dict[str, list[str]]:
    """
    Combine parent+clone rows per category, then:
      - keep undated rows in GH encounter order,
      - sort dated rows oldest→newest (X→0 floor),
    Append per-row provenance ONLY when the category mixes parent+clone.
    """
    if not isinstance(ports_obj, dict):
        return {}

    out: dict[str, list[str]] = {}

    # 1) Detect mixing per category
    cat_roles: dict[str, set[str]] = {}
    
    def _scan_source(source: dict, role: str):
        """Mark which role (parent/clone) contributes rows per category into cat_roles."""        
        cats = (source or {}).get("categories") or {}
        for cat_key, rows in cats.items():
            if rows:
                cat_roles.setdefault(cat_key, set()).add(role)

    if ports_obj.get("parent_source"):
        _scan_source(ports_obj["parent_source"], "parent")
    for cs in (ports_obj.get("clone_sources") or []):
        _scan_source(cs, "clone")

    # 2) Build a combined stream per category with a global encounter index (preserve GH order)
    combined: dict[str, list[tuple[int, str, dict]]] = {}  # cat -> [(enc_ix, role, row)]
    enc_ix = 0

    def _append_source(source: dict, role: str):
        """Append rows from a source into the combined stream, preserving GH encounter order."""        
        nonlocal enc_ix
        cats = (source or {}).get("categories") or {}
        # Dicts keep GH order; rows are in GH order inside each category
        for cat_key, rows in cats.items():
            bucket = combined.setdefault(cat_key, [])
            for r in (rows or []):
                bucket.append((enc_ix, role, r))
                enc_ix += 1

    if ports_obj.get("parent_source"):
        _append_source(ports_obj["parent_source"], "parent")
    for cs in (ports_obj.get("clone_sources") or []):
        _append_source(cs, "clone")

    # 3) For each category, split undated/dated, keep undated order, sort dated by date key (tiebreak: enc_ix)
    for cat_key, triples in combined.items():
        disp_cat = _title_case_words(cat_key)
        bucket = out.setdefault(disp_cat, [])
        mixed = (cat_roles.get(cat_key) == {"parent", "clone"})

        undated = []
        dated   = []
        for enc, role, r in triples:
            date = (r.get("date") or "").strip()
            if date:
                dated.append((enc, role, r, _date_sort_key(date, enc)))
            else:
                undated.append((enc, role, r))

        dated.sort(key=lambda t: t[3])  # sort by computed key

        ordered = [ (enc, role, r) for (enc, role, r) in undated ] + \
                  [ (enc, role, r) for (enc, role, r, _) in dated ]

        # 4) Render lines (unchanged formatting rules)
        for enc, role, r in ordered:
            is_parent = (role == "parent")

            regions = _format_regions(r.get("regions"))
            platform = (r.get("platform") or "").strip()
            tags = _format_additional_tags(r.get("additional_tags"))
            title = (r.get("title") or "").strip()
            date  = (r.get("date") or "").strip()
            pub   = (r.get("publisher") or "").strip()
            models_in = _format_models_bracketed(r.get("model"))
            machine = (r.get("machine") or "").strip()

            parts: list[str] = []
            parts.append(regions)

            plat_seg = f"{platform}{tags}"
            if title:
                parts.append(plat_seg)
            else:
                parts.append(f"{plat_seg} {models_in}".strip())

            if title:
                safe_title = title.replace('"', '\\"')
                if models_in:
                    parts.append(f"\"{safe_title} {models_in}\"")
                else:
                    parts.append(f"\"{safe_title}\"")

            if date:
                parts.append(f"({date})")
            if pub:
                parts.append(f"by {pub}")

            left = " ".join(p for p in parts if p)

            comment = (r.get("comment") or "").strip()
            if mixed:
                comment = _append_provenance_comment(comment, is_parent_row=is_parent, machine=machine)

            line = f"{left} : {comment}" if comment else left
            bucket.append(line)

    return out

def _read_gh_ports(path: Path) -> dict:
    """Read a GH ports JSON file and return a dict (or {} on failure)."""    
    data = _read_json(path)
    return data if isinstance(data, dict) else {}

def _is_valid_port_row(row: dict) -> bool:
    """Return True if a GH port row has a non-empty 'platform' string."""
    plat = (row or {}).get("platform")
    return isinstance(plat, str) and plat.strip() != ""

def _norm_regions(regs) -> list[str]:
    """Normalise regions to a non-empty list of strings, defaulting to ['??']."""
    if not regs:
        return ["??"]
    out = []
    for r in regs:
        if isinstance(r, str) and r.strip():
            out.append(r.strip())
    return out or ["??"]

def _norm_tags(tags) -> list[str]:
    """Return a cleaned list of non-empty 'additional_tags' strings."""
    out = []
    for t in (tags or []):
        if isinstance(t, str) and t.strip():
            out.append(t.strip())
    return out

def _collect_valid_ports_by_category(
    gh_entry: dict, 
    source_machine: str, 
    source_gh_id: int | None = None
) -> dict[str, list[dict]]:
    """
    Normalise valid GH port rows grouped by category for a single GH source.

    Args:
        gh_entry: The GH entry dict for one machine (e.g., gh_ports['puckman']).
        source_machine: The MAME shortname this GH entry belongs to (provenance).
        source_gh_id: The GH numeric id (if present) for this source; copied to every row.

    Returns:
        Dict mapping category -> list of normalised row dicts. Every row includes:
        - 'machine' : provenance MAME shortname
        - 'gh_id'   : the GH id we got from gh_entry (may be None)
        - 'platform', 'regions', 'model', 'title', 'date', 'publisher',
          'comment', 'additional_tags'
    """
    cats = {}
    ports = (gh_entry or {}).get("ports") or {}
    if not isinstance(ports, dict):
        return cats

    for cat, rows in ports.items():
        if not isinstance(rows, list):
            continue
        out_rows = []
        for r in rows:
            if not isinstance(r, dict) or not _is_valid_port_row(r):
                continue
            out_rows.append({
                "machine": source_machine,
                "gh_id": source_gh_id,
                "platform": r.get("platform"),
                "regions": _norm_regions(r.get("regions")),
                "model": r.get("model") or [],
                "title": r.get("title"),
                "date": r.get("date"),
                "publisher": r.get("publisher"),
                "comment": r.get("comment"),
                "additional_tags": _norm_tags(r.get("additional_tags")),
            })
        if out_rows:
            cats[cat] = out_rows
    return cats

def _gh_keys_with_any_valid_ports(gh_ports: dict) -> set[str]:
    """All GH shortnames that have at least one valid row in any category."""
    out = set()
    for key, entry in gh_ports.items():
        cats = _collect_valid_ports_by_category(entry, key, (entry or {}).get("gh_id"))
        if any(cats.values()):
            out.add(key)
    return out

def _build_ports_for_parent(parent: str,
                            parents_map: dict[str, list],
                            gh_ports: dict) -> tuple[dict | None, set[str], bool]:
    """
    Returns (ports_obj_or_None, clones_with_ports_set, parent_has_ports_bool).
    ports_obj = {
      "parent_source": { "machine": parent, "gh_id": <int or None>, "categories": {...} }   # only if any rows
      "clone_sources": [ { "machine": clone, "gh_id": <int or None>, "categories": {...} }, ... ]
    }
    """
    ports_obj: dict = {"clone_sources": []}
    clones_with_ports: set[str] = set()
    parent_has_ports = False

    # Parent source
    p_entry = gh_ports.get(parent)
    if isinstance(p_entry, dict):
        p_cats = _collect_valid_ports_by_category(p_entry, parent, p_entry.get("gh_id"))
        if any(p_cats.values()):
            ports_obj["parent_source"] = {
                "machine": parent,
                "gh_id": p_entry.get("gh_id"),
                "categories": p_cats,
            }
            parent_has_ports = True

    # Clone sources
    for clone in (parents_map.get(parent) or []):
        c_entry = gh_ports.get(clone)
        if not isinstance(c_entry, dict):
            continue
        c_cats = _collect_valid_ports_by_category(c_entry, clone, c_entry.get("gh_id"))
        if any(c_cats.values()):
            ports_obj["clone_sources"].append({
                "machine": clone,
                "gh_id": c_entry.get("gh_id"),
                "categories": c_cats,
            })
            clones_with_ports.add(clone)


    if not parent_has_ports and not ports_obj["clone_sources"]:
        return None, clones_with_ports, False

    return ports_obj, clones_with_ports, parent_has_ports

def _control_type_label(raw_type: str | None) -> str:
    """Map a raw MAME control type to a human-readable label (fallback to title-case)."""    
    t = (raw_type or "").strip().lower()
    return _CONTROL_TYPE_LABELS.get(t, t.title() if t else "Unknown Control")

def _ways_pretty(raw: str | None) -> str:
    """
    Turn ways/ways2/ways3 into user-friendly tokens.
    Examples:
      '8'            -> '8-way'
      '3 (half4)'    -> '3-of-4-way'
      '5 (half8)'    -> '5-of-8-way'
      'vertical2'    -> '2-way'
      'strange2'     -> '2-way'
    Fallbacks:
      - int-like strings -> '<N>-way'
      - otherwise return as-is.
    """
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s in {"vertical2", "strange2"}:
        return "2-way"
    # half patterns
    m = re.match(r"^(\d+)\s*\(half(\d+)\)$", s)
    if m:
        return f"{m.group(1)}-of-{m.group(2)}-way"
    # plain integer?
    if s.isdigit():
        return f"{int(s)}-way"
    return raw.strip()

def _ways_label(ways: str | None, ways2: str | None, ways3: str | None) -> str:
    """Combine ways/ways2/ways3 into a comma-separated label like '2-way, 8-way'."""    
    parts = [p for p in map(_ways_pretty, (ways, ways2, ways3)) if p]
    return ", ".join(parts)

def _control_line_from_row(row: dict) -> str:
    """
    Line describing the controller itself (without buttons), e.g.:
      '4-way Joystick'
      '2-way, 8-way Dual Joystick'
      'Trackball'
    """
    typ = _control_type_label(row.get("type"))
    ways = _ways_label(row.get("ways"), row.get("ways2"), row.get("ways3"))
    return f"{ways} {typ}".strip() if ways else typ

def _buttons_count_from_rows(rows: list[dict]) -> int:
    """Sum 'buttons' across a player's rows; ignore reqbuttons per your call."""
    total = 0
    for r in rows:
        try:
            n = int(r.get("buttons")) if r.get("buttons") is not None else 0
        except Exception:
            n = 0
        total += max(0, n)
    return total

def _pluralise(singular: str, n: int, plural: str | None = None) -> str:
    """Return singular or plural form based on n, using a custom plural when provided."""    
    return singular if int(n or 0) == 1 else (plural or f"{singular}s")


def _orientation_from_rotate(rot) -> str | None:
    """Convert MAME rotate degrees to 'Horizontal'/'Vertical', or None if unknown."""    
    try:
        r = int(rot)
    except Exception:
        return None
    if r in (0, 180):
        return "Horizontal"
    if r in (90, 270):
        return "Vertical"
    return None

def _type_title(s: str | None) -> str:
    """Normalise a display type token to title-case with known aliases (Raster/Vector/SVG/LCD)."""    
    s = (s or "").strip().lower()
    if s == "raster": return "Raster"
    if s == "vector": return "Vector"
    if s == "svg":    return "SVG"
    if s == "lcd":    return "LCD"
    return s.title() if s else ""

def _format_hz_3dp(hz) -> str | None:
    """Format a numeric frequency as 'N.NNN Hz' or return None on invalid/zero input."""    
    try:
        v = float(hz)
    except Exception:
        return None
    if v <= 0:
        return None
    return f"{v:.3f} Hz"


def _build_controls_section(players: int | None, controls: list[dict] | None) -> dict:
    """
    Build the controls block.

    Rules:
    - Group raw control rows by player; collapse duplicate control lines with “(Nx) …”.
    - Sum buttons per player as an integer.
    - If there are no control rows:
        * If players > 0: emit placeholder entries for players 1..players
          with ["Unknown controls"] and buttons=0.
        * If players == 0 (or unknown): per_player MUST be [] (no placeholders).
    - If some rows exist but fewer than 'players', fill missing players (up to 'players')
      with placeholders (buttons=0).

    Returns: {"players": <int>, "per_player": [ {player, control_lines, buttons}, ... ]}
    """
    # Normalise player count
    try:
        pcount = int(players) if players is not None else 0
    except Exception:
        pcount = 0

    # Bucket rows by player index
    bucket: dict[int, list[dict]] = {}
    for row in (controls or []):
        try:
            p = int(row.get("player"))
        except Exception:
            p = 1
        bucket.setdefault(p, []).append(row)

    per_player: list[dict] = []

    # Build concrete entries for players that have ≥1 raw row
    for p in sorted(bucket.keys()):
        rows = bucket[p]
        raw_lines = [_control_line_from_row(r) for r in rows]
        counts = Counter(l.casefold() for l in raw_lines)
        order = list(dict.fromkeys(raw_lines))  # preserve first-seen order/case
        control_lines = [
            (f"({counts[l.casefold()]}x) {l}" if counts[l.casefold()] > 1 else l)
            for l in order
        ]
        btn_total = _buttons_count_from_rows(rows)  # integer
        per_player.append({
            "player": p,
            "control_lines": control_lines,
            "buttons": btn_total
        })

    # Helper for placeholders (buttons must be int per schema)
    def _placeholder(p: int) -> dict:
        return {"player": p, "control_lines": ["Unknown controls"], "buttons": 0}

    # If no rows at all:
    if not per_player:
        if pcount > 0:
            per_player = [_placeholder(p) for p in range(1, pcount + 1)]
        else:
            # players == 0: leave empty (no controllers in partially emulated titles)
            return {"players": 0, "per_player": []}
        return {"players": pcount, "per_player": per_player}

    # Some rows exist: fill gaps up to declared player count
    if pcount > 0:
        present = {e["player"] for e in per_player}
        for p in range(1, pcount + 1):
            if p not in present:
                per_player.append(_placeholder(p))
        per_player.sort(key=lambda e: e["player"])

    return {"players": pcount, "per_player": per_player}


def _controls_section_to_display(section: dict) -> str:
    """
    Format:
      Players: N
      Player 1
      <each control line>
      <Buttons line>
      Player 2
      ...
    """
    lines: list[str] = []
    lines.append(f"Players: {section.get('players', 0)}")

    for pp in section.get("per_player", []):
        lines.append(f"Player {pp.get('player')}")
        for l in (pp.get("control_lines") or []):
            lines.append(l)
        btns = int(pp.get("buttons") or 0)
        lines.append("No Buttons" if btns <= 0 else f"{btns} {_pluralise('Button', btns)}")

    return "\n".join(lines)




def _build_displays_section(displays: list[dict] | None, display_count: int | None):
    """
    Group identical screens by (type, orientation, width, height, refresh_3dp).
    Width/height are ignored for Vector/SVG (set to None in the grouping key).

    Returns:
    {
      "heading": "Screen"|"Screens",
      "count": <total_screens>,
      "groups": [
        {
          "count": n,
          "type": "Raster"|"Vector"|"SVG"|"LCD",
          "orientation": "Horizontal"|"Vertical"|"",
          "width": 320|None,
          "height": 224|None,
          "refresh": "59.640 Hz"|None
        },
        ...
      ]
    }
    """
    disp_list = displays or []
    groups: dict[tuple, int] = {}

    for d in disp_list:
        typ = _type_title(d.get("type"))
        ori = _orientation_from_rotate(d.get("rotate")) or ""

        hz_str = _format_hz_3dp(d.get("refresh_hz"))

        # Width/height only meaningful for Raster/LCD
        w = h = None
        if typ in {"Raster", "LCD"}:
            try:
                w = int(d.get("width"))
                h = int(d.get("height"))
                if not (w > 0 and h > 0):
                    w = h = None
            except Exception:
                w = h = None

        key = (typ, ori, w, h, hz_str)
        groups[key] = groups.get(key, 0) + 1

    # total count: take MAME's display_count if sensible, otherwise sum of groups
    try:
        cnt = int(display_count) if display_count is not None else 0
    except Exception:
        cnt = 0
    if cnt <= 0:
        cnt = sum(groups.values())

    # stable order: by type, orientation, width, height, refresh string
    def _ord_key(kv):
        (typ, ori, w, h, hz) = kv[0]
        return (typ or "", ori or "", w or 0, h or 0, hz or "")

    grouped_list = []
    for (typ, ori, w, h, hz), c in sorted(groups.items(), key=_ord_key):
        grouped_list.append({
            "count": c,
            "type": typ or "",
            "orientation": ori,
            "width": w,
            "height": h,
            "refresh": hz,
        })

    return {
        "heading": _pluralise("Screen", cnt),
        "count": cnt,
        "groups": grouped_list,
    }


def _displays_section_to_display(section: dict) -> str:
    """
    Render a human-readable block describing the machine's video displays.

    Input shape (as produced by _build_displays_section):
        {
          "heading": "Screen" | "Screens",
          "count": <int>,  # total number of screens
          "groups": [
            {
              "count": <int>,              # how many identical screens in this group
              "type": "Raster"|"Vector"|"SVG"|"LCD",
              "orientation": "Horizontal"|"Vertical"|"",
              "width": <int|None>,         # only for Raster/LCD
              "height": <int|None>,        # only for Raster/LCD
              "refresh": "59.640 Hz"|None  # already formatted to 3dp
            },
            ...
          ]
        }

    Output format (newline-separated):
        - First line: "<heading>: <count>" where heading is "Screen" or "Screens".
        - Then, for each group (in the order provided):
            * A line with the screen type and optional orientation, prefixed with
              "(Nx) " if the whole group has multiplicity > 1, for example:
                  "Raster (Horizontal)"
                  "(2x) LCD (Vertical)"
            * If width/height are present, a line "W x H pixels".
            * If a refresh string is present, a line like "59.640 Hz".

    Rules and edge cases:
        - Orientation is omitted when blank.
        - Resolution lines appear only for Raster/LCD where width and height are known.
        - Refresh is omitted if missing.
        - The function assumes the input dict is already validated and grouped
          by _build_displays_section.
    """
    lines: list[str] = []
    heading = section.get("heading") or "Screen"
    count = section.get("count") or 0
    lines.append(f"{heading}: {count}")

    for g in section.get("groups", []):
        c   = g.get("count", 1)
        typ = g.get("type", "")
        ori = g.get("orientation", "")
        w   = g.get("width")
        h   = g.get("height")
        hz  = g.get("refresh")

        # Type + orientation (prefix multiplicity only if this *whole group* is duplicated)
        type_label = typ + (f" ({ori})" if ori else "")
        if c > 1:
            lines.append(f"({c}x) {type_label}")
        else:
            lines.append(type_label)

        # Resolution only for Raster/LCD (width/height present)
        if w is not None and h is not None:
            lines.append(f"{w} x {h} pixels")

        # Refresh if available
        if hz:
            lines.append(hz)

    return "\n".join(lines)


def _build_chips_section(chips: list[dict] | None,
                         sound_channels: int | None,
                         device_ref):
    """
    Return a structured 'chips' dict ready for JSON:

    {
      "cpus": {
        "heading": "CPU" | "CPUs",
        "count": <int>,
        "items": ["(2x) Motorola 68000 @ 12.000 MHz", ...]
      },
      "audio_chips": {
        "heading": "Audio Chip" | "Audio Chips",
        "count": <int>,
        "items": ["(2x) Yamaha YM2151 @ 3.580 MHz", "OKI MSM6295", ...]
      },
      "requires_samples": true|false,
      "audio_channels": <int or 0>,
      "speakers": <int or 0>
    }

    Rules:
    - Exclude 'Speaker' and 'Samples'/'Sample' from audio_chips list.
    - Count speakers separately in 'speakers'.
    - '(Nx)' multiplicity applied to identical labels.
    """
    cpu_labels_raw: list[str] = []
    audio_chip_labels_raw: list[str] = []
    speaker_count = 0

    for ch in (chips or []):
        typ = (ch.get("type") or "").strip().lower()
        name_raw = (ch.get("name") or "").strip()
        clk = ch.get("clock_hz")
        name_ci = name_raw.casefold()

        if typ == "cpu":
            cpu_labels_raw.append(_chip_label(name_raw, clk))
            continue

        if typ == "audio":
            if name_ci == "speaker":
                speaker_count += 1
                continue
            if name_ci in {"samples", "sample"}:
                # confirmation comes via requires_samples below
                continue
            audio_chip_labels_raw.append(_chip_label(name_raw, clk))
            continue

        # Unknown types ignored

    cpu_items = _prefix_multiples(cpu_labels_raw)
    audio_items = _prefix_multiples(audio_chip_labels_raw)

    # Headings use the pre-collapse counts for natural language
    cpu_heading = _pluralise("CPU", len(cpu_labels_raw))
    audio_heading = _pluralise("Audio Chip", len(audio_chip_labels_raw), "Audio Chips")

    # Channels/samples
    try:
        chn = int(sound_channels) if sound_channels is not None else 0
    except Exception:
        chn = 0
    requires_samples = _has_samples_flag(device_ref)

    return {
        "cpus": {
            "heading": cpu_heading,
            "count": len(cpu_labels_raw),
            "items": cpu_items,
        },
        "audio_chips": {
            "heading": audio_heading,
            "count": len(audio_chip_labels_raw),
            "items": audio_items,
        },
        "requires_samples": bool(requires_samples),
        "audio_channels": chn,
        "speakers": int(speaker_count),
    }



def _hz_to_human(n: int | float | None) -> tuple[float, str] | None:
    """1000-based Hz units. Returns (value, unit) or None; formatted later to 3dp."""
    if not n:
        return None
    try:
        v = float(n)
    except (TypeError, ValueError):
        return None
    if v < 1.0:
        return None
    GHz = 1_000_000_000.0
    MHz = 1_000_000.0
    kHz = 1_000.0
    if v >= GHz: return (v / GHz, "GHz")
    if v >= MHz: return (v / MHz, "MHz")
    if v >= kHz: return (v / kHz, "kHz")
    return (v, "Hz")


def _chip_label(name: str | None, clock_hz) -> str:
    """e.g. 'Zilog Z80 @ 3.870 MHz' or 'Yamaha YM2151' if no clock."""
    nm = (name or "").strip()
    h = _hz_to_human(clock_hz)
    return f"{nm} @ {h[0]:.3f} {h[1]}" if h else nm


def _prefix_multiples(labels: list[str]) -> list[str]:
    """
    Collapse duplicates with '(Nx)' per project style.
    - Case-insensitive counting
    - Preserve first-seen order/casing
    """
    labels = [l for l in labels if l]
    counts = Counter(l.casefold() for l in labels)
    first_seen_unique = list(dict.fromkeys(labels))
    out = []
    for lab in first_seen_unique:
        n = counts[lab.casefold()]
        out.append(f"({n}x) {lab}" if n > 1 else lab)
    return out


def _sum_device_speakers(device_ref) -> int:
    """Sum 'speaker' across device_ref entries. Non-int/missing treated as 0."""
    if not isinstance(device_ref, (list, tuple)):
        return 0
    total = 0
    for d in device_ref:
        try:
            total += int(d.get("speaker", 0))
        except Exception:
            continue
    return total


def _has_samples_flag(device_ref) -> bool:
    """True if any device_ref entry has samples == 'yes' (case-insensitive)."""
    if not isinstance(device_ref, (list, tuple)):
        return False
    for d in device_ref:
        s = (d.get("samples") or "").strip().lower()
        if s in {"yes", "true", "1", "y"}:
            return True
    return False


def _format_chips_and_audio_block(chips: list[dict] | None,
                                  sound_channels: int | None,
                                  device_ref) -> str:
    """
    Order and rules:
      CPU: ...
      Audio: ...                (exclude 'Speaker' and 'Samples'/'Sample')
      Requires additional samples   (if any device_ref[].samples == 'yes')
      Audio channels: N             (if N > 0)
      (Nx) Speaker                  (if any counted)

    - Multiplicity '(Nx)' applied to identical rendered labels (case-insensitive).
    - 'tag' is ignored entirely.
    """
    cpu_labels: list[str] = []
    audio_chip_labels: list[str] = []
    speaker_count = 0

    for ch in (chips or []):
        typ = (ch.get("type") or "").strip().lower()
        name_raw = (ch.get("name") or "").strip()
        clk = ch.get("clock_hz")

        # Normalise name for rules but preserve original casing in labels
        name_ci = name_raw.casefold()

        if typ == "cpu":
            cpu_labels.append(_chip_label(name_raw, clk))
            continue

        if typ == "audio":
            if name_ci == "speaker":
                # Count speakers; do not list as an audio chip
                speaker_count += 1
                continue
            if name_ci in {"samples", "sample"}:
                # Do not list as an audio chip; samples requirement is handled below
                continue
            # Regular audio chip/device
            audio_chip_labels.append(_chip_label(name_raw, clk))
            continue

        # Unknown types: ignore for now

    lines: list[str] = []

    if cpu_labels:
        lines.append("CPU: " + ", ".join(_prefix_multiples(cpu_labels)))

    if audio_chip_labels:
        lines.append("Audio: " + ", ".join(_prefix_multiples(audio_chip_labels)))

    # Samples requirement (from device_ref)
    if _has_samples_flag(device_ref):
        lines.append("Requires additional samples")

    # Report channel count if present
    try:
        chn = int(sound_channels) if sound_channels is not None else 0
    except Exception:
        chn = 0
    if chn > 0:
        lines.append(f"Audio channels: {chn}")

    # Speaker line at the very end
    if speaker_count > 0:
        lines.append(f"({speaker_count}x) Speaker")

    return "\n".join(lines)


def _order_media_labels(labels: list[str]) -> list[str]:
    """Return media labels sorted by project precedence, then A→Z for ties."""
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
    """Map raw device tokens to friendly media labels, de-duplicated in input order."""
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
    """Join items as 'A'; 'A & B'; or 'A, B & C' without trimming."""
    n = len(items)
    if n == 0:
        return ""
    if n == 1:
        return items[0]
    if n == 2:
        return f"{items[0]} & {items[1]}"
    return f"{', '.join(items[:-1])} & {items[-1]}"

def _split_outside_parens(s: str) -> list[str]:
    """Split on '/' only when outside parentheses, preserving inner groups."""
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


def _format_rom_block(rom_count: int,
                      rom_bytes_total: int,
                      disk_required: str | None,
                      disk_regions) -> str:
    """
    Build the three-line ROM/media summary used in the wiki infobox.

    Lines:
      1) "<N> ROM" or "<N> ROMs" with thousands separators, for example:
           "6 ROMs"
      2) "<bytes> bytes" followed by a binary-unit parenthetical where applicable
         (KiB, MiB, GiB) to 2dp, for example:
           "7,413,760 bytes (7.07 MiB)"
         Values under 1024 bytes omit the parenthetical.
      3) Optional "Plus: <media>" line, only when disk_required == "yes".
         The media portion is a human-friendly join (A & B & C) of device labels,
         each optionally prefixed with "(Nx)" when the same medium appears multiple
         times in the raw device list.

    Media mapping and ordering:
      - Raw device tokens from disk_regions (strings like "cdrom", "dvdrom1", "gdrom",
        "laserdisc1", "cf", "sdcard", "hdd", etc.) are normalised via
        _normalise_device_to_media to labels such as "CD-ROM", "DVD-ROM", "GD-ROM",
        "LaserDisc", "Hard disk", "CompactFlash card", "Secure Digital card".
      - Unknown or non-media tokens are ignored.
      - Multiplicity is counted case-insensitively and rendered as "(Nx) Label"
        only when N > 1, for example "(2x) CD-ROM".
      - Unique labels are ordered by project precedence using _order_media_labels,
        then alphabetically for ties.
      - Labels are joined with join_with_ampersand for final display.

    Parameters:
        rom_count        Number of ROM files reported by MAME.
        rom_bytes_total  Sum of ROM sizes in bytes.
        disk_required    "yes" or "no" (truthy check is case-insensitive); only "yes"
                         triggers the Plus line.
        disk_regions     A string or list of raw device tokens that indicate additional
                         media (for example ["cdrom", "dvdrom1", "laserdisc2"]).

    Returns:
        A single string with 2 or 3 lines as described above.

    Notes:
        - disk_regions may be a single string or a list; both are supported.
        - If disk_required is "yes" but no valid media can be mapped, the Plus line
          is omitted.
        - Thousands separators are applied to byte counts and ROM totals for readability.
    """
    
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
            ordered_unique = _order_media_labels(first_seen_unique)

            # Render with “(Nx)” prefix when N>1
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
    """Split on '/' outside parentheses and join parts with '&' per house style."""    
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
        "year": pinfo.get("year"),
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
    for c in sorted(clones):
        minfo = mame.get(c, {})
        out.append({
            "machine": c,
            "title": _raw_mame_title(minfo, c),
            "year": minfo.get("year"),
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
    """Read JSON from path and return the parsed object; on error, log and return None."""    
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to read {path}: {e}")
        return None


def _write_json(path: Path, obj: Any) -> bool:
    """Write obj as pretty-printed JSON to path (creating parents); return True on success."""    
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        log.info(f"Wrote {path}")
        return True
    except Exception as e:
        log.error(f"Failed to write {path}: {e}")
        return False


def _project_for_wiki(rec: dict) -> dict:
    """
    Site-facing: slim, preformatted fields only.
    Keep only what ExoticA will ingest or render.
    """
    out = {}
    # Always keep identification
    if rec.get("wiki_page_name"): out["wiki_page_name"] = rec["wiki_page_name"]
    
    out["wiki_redirects"] = rec.get("wiki_redirects", [])

    if rec.get("year") is not None: out["year"] = rec["year"]
    
    if rec.get("manufacturer") is not None: out["manufacturer"] = rec["manufacturer"]

    if rec.get("mame_titles_display"):
        out["mame_titles_display"] = rec["mame_titles_display"]

    # Preformatted convenience blocks (include only if present)
    for k in ("roms_display", "chips_display", "displays_display", "controls_display"):
        if rec.get(k): out[k] = rec[k]

    # Ports: wiki shows ONLY the single-line view
    if rec.get("ports_display"):
        out["ports_display"] = rec["ports_display"]

    if rec.get("gh_ids"):
        out["gh_ids"] = rec["gh_ids"]

    return out


def _project_for_raw(machine: str, rec: dict) -> dict:
    """
    Review-facing: rich, structured, no preformatted strings.
    Include per-variable fields for inspection and future renderers.
    """
    out = {}

    # Identification & provenance
    out["machine"] = machine
    if rec.get("wiki_page_name"): out["wiki_page_name"] = rec["wiki_page_name"]
    
    # Surface redirects as an unprefixed list
    out["wiki_redirects"] = rec.get("wiki_redirects", [])

    if rec.get("mame_titles"): out["mame_titles"] = rec["mame_titles"]

    # Title parsing (full structured description)
    if rec.get("description"): out["description"] = rec["description"]

    # Year/manufacturer
    if rec.get("year") is not None: out["year"] = rec["year"]
    
    if rec.get("manufacturer") is not None: out["manufacturer"] = rec["manufacturer"]

    # ROM/media raw stats (carry raw inputs; skip roms_display)
    for k in ("rom_count", "rom_bytes_total", "disk_required", "disk_regions"):
        if k in rec: out[k] = rec[k]

    # Chips / displays / controls: keep structured only
    if rec.get("chips"): out["chips"] = rec["chips"]
    if rec.get("displays"): out["displays"] = rec["displays"]
    if rec.get("controls"): out["controls"] = rec["controls"]

    # Ports (structured, when present)
    if rec.get("ports"): out["ports"] = rec["ports"]

    # Classifications & flags (useful for QA)
    for k in ("game_status", "category", "type", "isbios", "isdevice", "ismechanical", "requires_samples"):
        if k in rec: out[k] = rec[k]

    if rec.get("gh_ids"): out["gh_ids"] = rec["gh_ids"]

    return out


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
# TITLE PARSING
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

    def split_top_level(text: str, delim: str) -> List[str]:
        """Split text on delim only at top level (ignoring bracketed regions)."""        
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
    """End-to-end transform: load artefacts, build parent-centric records, write wiki/raw JSON."""
    started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    t0 = time.perf_counter()
        
    # --- Stage stamp: skip unchanged ---
    stamp_dir = DATA_DIR / ".stamps"
    stamp_dir.mkdir(parents=True, exist_ok=True)
    stamp_path = stamp_dir / "transform.json"

    # Inputs that determine transform outputs (tweak if your flow changes)
    stamp_inputs = [
        MAME_MACHINES_PATH,
        INI_CLASS_PATH,
        PARENT_INDEX_PATH,
        GH_SYSTEM_PORTS_PATH,
        DATA_DIR / "mame_parsing_summary.json",
        DATA_DIR / "history_parsing_summary.json",
        DATA_DIR / "ini_parsing_summary.json",
        DATA_DIR / "title_overrides.json",
    ]

    current_stamp = make_stamp(
        schema_id="mht.stage.transform",
        tool_version=tool_version("transformer"),
        inputs=stamp_inputs,
        # Optional knobs that should invalidate the cache when logic changes:
        #extra={"selection_rules": "v1", "title_parser": "v1"},
    )

    prev = load_stamp(stamp_path)
    if is_fresh(current_stamp, prev):
        log.info("Transform stage up-to-date (stamp matched) — skipping transform")
        return True    

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
    overrides_stats = {"configured": len(overrides), "eligible": 0, "applied": 0}

    # Load required inputs
    mame = _read_json(MAME_MACHINES_PATH)
    ini_map = _read_json(INI_CLASS_PATH)
    parent_index = _read_json(PARENT_INDEX_PATH)
    gh_ports = _read_gh_ports(GH_SYSTEM_PORTS_PATH)
    gh_keys_with_ports = _gh_keys_with_any_valid_ports(gh_ports)

    if not isinstance(mame, dict) or not isinstance(ini_map, dict) or not isinstance(parent_index, dict):
        log.error("Missing or invalid inputs; aborting transform.")
        return False

    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})

    # --- Read stage summaries (sources of truth for versions) ---
    mame_sum = _read_json(DATA_DIR / "mame_parsing_summary.json") or {}
    hist_sum = _read_json(DATA_DIR / "history_parsing_summary.json") or {}
    ini_sum  = _read_json(DATA_DIR / "ini_parsing_summary.json") or {}

    # Small helper for nested dict access (header-first fallbacks)
    def _get(d, *path, default=None):
        cur = d
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    # Prefer new header.versions; fall back to legacy blocks for compatibility
    mame_build_val       = _get(mame_sum, "header", "versions", "mame_build")       or _get(mame_sum, "mame", "build")
    history_version_val  = _get(hist_sum, "header", "versions", "gh_version")       or _get(hist_sum, "history", "version")
    history_date_val     = _get(hist_sum, "header", "versions", "gh_date")          or _get(hist_sum, "history", "date")
    ini_generated_at_val = _get(ini_sum,  "header", "generated_at")                  or _get(ini_sum,  "ini", "generated_at")

    # Raw versions for the transform summary (audit-only echo)
    versions = {
        "mame_build":       mame_build_val,
        "history_version":  history_version_val,
        "history_date":     history_date_val,
        "ini_generated_at": ini_generated_at_val,
    }

    # --- Build wiki header versions using creators' schemes (no mismatch reporting here) ---
    # e.g. mame_build_raw: "0.281 (mame0281)" -> mame_core: "0.281"
    mame_build_raw   = mame_build_val
    mame_core        = _core(mame_build_raw) or _get(mame_sum, "header", "versions", "mame_xml_version")
    hist_version_raw = history_version_val

    # Per-INI versions: tolerate current and older shapes
    ini_versions_raw: dict[str, str] = {}
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
        files_list = ini_sum.get("files")
        if isinstance(files_list, list):
            for item in files_list:
                fn = (item.get("filename") or item.get("path") or "").strip()
                v  = item.get("version") or {}
                ver = v.get("mame_version") or v.get("raw") or "Unknown"
                if fn:
                    ini_versions_raw[fn] = ver

    if not ini_versions_raw:
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

    # --- QA: duplicate ports across parent/clone (parents only) ---
    systems_with_parent_clone_port_dupes = 0
    systems_with_parent_clone_port_dupes_list: list[str] = []


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
    _IGNORED_TOP_N = 25

    # --- Audio QA tallies (parents only) ---
    audio_total_with_channels = 0
    audio_channel_speaker_mismatch = 0
    audio_mismatch_examples: list[dict] = []
    audio_samples_required_count = 0

    # --- GH port tallies 
    parents_with_ports_count = 0
    clones_with_ports_set: set[str] = set()


    for name in sorted(included_parents):
        minfo = mame.get(name)
        if not minfo:
            continue

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

        raw_man = minfo.get("manufacturer") or ""
        manufacturer_display = join_with_ampersand(_split_outside_parens(raw_man))

        # ROM summary (data already parsed upstream)
        rom_count       = int(minfo.get("rom_count") or 0)
        rom_bytes_total = int(minfo.get("rom_bytes_total") or 0)
        disk_required = minfo.get("disk_required")  # "yes" / "no"
        disk_regions  = minfo.get("disk_regions")   # list (per your schema)

        # Normalise raw device names to display media labels
        roms_display = _format_rom_block(rom_count, rom_bytes_total, disk_required, disk_regions)

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
                    

        # --- Chips / Audio block + QA tallies ---
        chips_section = _build_chips_section(
            minfo.get("chips"),
            minfo.get("sound_channels"),
            minfo.get("device_ref"),
        )

        displays_section = _build_displays_section(
            minfo.get("displays"),
            minfo.get("display_count")
        )
        displays_display = _displays_section_to_display(displays_section)


        controls_section = _build_controls_section(
            minfo.get("players"),
            minfo.get("controls"),
        )
        controls_display = _controls_section_to_display(controls_section)

        reported_channels = minfo.get("sound_channels")
        speaker_sum = _sum_device_speakers(minfo.get("device_ref"))

        # Count machines where a channel count is reported (>0)
        try:
            chn = int(reported_channels) if reported_channels is not None else 0
        except Exception:
            chn = 0

        if chn > 0:
            audio_total_with_channels += 1
            if speaker_sum != chn:
                audio_channel_speaker_mismatch += 1
                if len(audio_mismatch_examples) < 10:  # cap examples in summary
                    audio_mismatch_examples.append({
                        "machine": name,
                        "sound_channels": chn,
                        "speaker_sum": speaker_sum
                    })

        # Samples required?
        if _has_samples_flag(minfo.get("device_ref")):
            audio_samples_required_count += 1


        chips_disp = _render_chips_display(
            chips_section,
            requires_samples=_truthy_flag(minfo.get("requires_samples")),
            sound_channels=(int(reported_channels) if reported_channels not in (None, "") else None),
            speaker_count=(int(speaker_sum) if speaker_sum not in (None, "") else None),
        )

        # Turn dict-of-lists into one newline-delimited string with pluralised headers
        cpus_lines = list(chips_disp.get("cpus") or [])
        audio_lines = list(chips_disp.get("audio_chips") or [])

        cpu_hdr   = f"{_pluralise('CPU', len(cpus_lines), 'CPUs')}:"
        audio_hdr = f"{_pluralise('Audio Chip', len(audio_lines), 'Audio Chips')}:"

        chips_display_block = "\n".join([cpu_hdr, *cpus_lines, audio_hdr, *audio_lines])

        ports_obj, clones_with_ports_local, parent_has_ports = _build_ports_for_parent(
            name, parents_map, gh_ports
        )

        # Final inclusion gate: keep this parent only if parent or any clone has ports
        if ports_obj is None:
            continue

        # --- Ensure ports schema always has both keys, even when empty ---
        # We keep behaviour the same (no new GH IDs introduced) by making
        # `parent_source` an empty dict when the parent had no rows.
        if not isinstance(ports_obj.get("clone_sources"), list):
            ports_obj["clone_sources"] = []
        if not isinstance(ports_obj.get("parent_source"), dict):
            ports_obj["parent_source"] = {}

        # Accumulate summary tallies
        clones_with_ports_set.update(clones_with_ports_local)
        if parent_has_ports:
            parents_with_ports_count += 1

        if _has_parent_clone_duplicate_ports(ports_obj):
            systems_with_parent_clone_port_dupes += 1
            systems_with_parent_clone_port_dupes_list.append(name)

        gh_ids = _gh_ids_from_ports_obj(ports_obj)

        record = {
            "wiki_page_name": wiki_page_name,
            "description": desc_fields,
            "year": minfo.get("year") if minfo.get("year") not in ("", None) else None,
            "manufacturer": manufacturer_display if manufacturer_display else None,
            # Preformatted
            "roms_display": roms_display,
            # Raw ROM/media stats
            "rom_count": rom_count,
            "rom_bytes_total": rom_bytes_total,
            "disk_required": disk_required,
            "disk_regions": disk_regions,
            
            "chips": chips_section,
            "chips_display": chips_display_block,
                                    
            "displays": displays_section,
            "displays_display": displays_display,
            "controls": controls_section,
            "controls_display": controls_display,

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
            
            "ports": ports_obj,
            
            "gh_ids": gh_ids,
        }


        # Build wiki-friendly list (no machine names)
        mt_disp = _render_mame_titles_display(record["mame_titles"])
        if mt_disp:
            record["mame_titles_display"] = mt_disp

        # ----------------- Build wiki_redirects (unprefixed) -----------------
        # Parent-derived redirects (titles/subtitles only; no versions)
        parent_redirects = _build_redirect_sources(desc_fields, wiki_page_name)

        # Clone-derived redirects ONLY for clones that actually appear in GH ports
        clone_redirects: list[str] = []
        for cs in (ports_obj.get("clone_sources") or []):
            c_machine = (cs or {}).get("machine")
            if not c_machine:
                continue
            clone_redirects.extend(_clone_primary_redirects(c_machine, mame, wiki_page_name))

        # Merge, normalise whitespace, de-dup case-insensitively, and exclude equals to page name
        merged_redirects: list[str] = []
        target_ci = (wiki_page_name or "").casefold()
        for s in (parent_redirects + clone_redirects):
            n = _collapse_ws(s)
            if n and n.casefold() != target_ci:
                merged_redirects.append(n)

        record["wiki_redirects"] = _dedupe_ci_preserve_order(merged_redirects)
        # ---------------------------------------------------------------------

        ports_display = _render_ports_display(name, ports_obj)
        if ports_display:
            record["ports_display"] = ports_display
        
        
        if _truthy_flag(minfo.get("isbios")):       included_flags["isbios"] += 1
        if _truthy_flag(minfo.get("isdevice")):     included_flags["isdevice"] += 1
        if _truthy_flag(minfo.get("ismechanical")): included_flags["ismechanical"] += 1

        out_map[name] = record

    # --- Write wiki output (header + games) ---
    wiki_doc = {
        "header": {
            "schema_id": SCHEMA_ID_WIKI,            # NEW
            "schema_version": SCHEMA_VER_WIKI,      # NEW
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "versions": wiki_header_versions,
        },
        "games": {m: _project_for_wiki(rec) for m, rec in out_map.items()}
    }
    ok_out_wiki = _write_json(WIKI_OUT_PATH, wiki_doc)

    # --- Write raw review output (header + games) ---
    raw_doc = {
        "header": {
            "schema_id": SCHEMA_ID_RAW,             # NEW
            "schema_version": SCHEMA_VER_RAW,       # NEW
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "versions": wiki_header_versions,
        },
        "games": {m: _project_for_raw(m, rec) for m, rec in out_map.items()}
    }
    ok_out_raw = _write_json(RAW_OUT_PATH, raw_doc)

    ok_out = ok_out_wiki and ok_out_raw


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
    sources_seen: dict[str, str] = {}


    for machine, rec in out_map.items():
        target = pages_map[machine]
        wiki_name = rec.get("wiki_page_name") or ""

        # Prefer the per-record list (already includes parent + GH-referenced clones).
        # Fallback to computed parent-only sources if, for any reason, it’s absent.
        sources = rec.get("wiki_redirects")
        if not sources:
            desc = rec.get("description") or {}
            sources = _build_redirect_sources(desc, wiki_name)

        for src in (sources or []):
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

    # Sort redirects for stability BEFORE embedding
    #redirects_map = dict(sorted(redirects_map.items(), key=lambda kv: kv[0].casefold()))

    # Sort for stability
    pages_map_sorted     = dict(sorted(pages_map.items(), key=lambda kv: kv[0].casefold()))
    redirects_map_sorted = dict(sorted(redirects_map.items(), key=lambda kv: kv[0].casefold()))
    page_names_list_sorted = sorted(page_names_list, key=str.casefold)

    generated_at_iso = datetime.datetime.utcnow().isoformat() + "Z"


    # Assemble and write file (stats near the top)
    wiki_pages_redirects = {
        "header": {
            "schema_id": SCHEMA_ID_PAGES,
            "schema_version": SCHEMA_VER_PAGES,
            "generated_at": generated_at_iso,
            #"versions": versions_block,
        },
        "prefix": WIKI_PREFIX,  # e.g. "Lost In Translation/"
        "stats": {
            "parents_total": len(out_map),
            "page_names_total": len(page_names_list_sorted),
            "redirects_total": len(redirects_map_sorted),
            "page_name_collisions": len(page_name_collisions),
            "redirect_conflicts": len(redirect_conflicts),
        },
        "pages": pages_map_sorted,            # { machine -> full path }
        "page_names": page_names_list_sorted, # [full path, ...]
        "redirects": redirects_map_sorted,    # { from -> to }
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
        "exotica_lit_wiki":         str(WIKI_OUT_PATH).replace("\\", "/"),
        "exotica_lit_raw_data":     str(RAW_OUT_PATH).replace("\\", "/"),   # NEW
        "wiki_pages_and_redirects": str(WIKI_PAGES_REDIRECTS_PATH).replace("\\", "/"),
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

    # Build the set of machines included in the export (parents + their clones)
    included_parents_set = set(out_map.keys())
    included_clones_set: set[str] = set()
    for p in included_parents_set:
        for c in (parents_map.get(p) or []):
            included_clones_set.add(c)

    included_all = included_parents_set | included_clones_set

    # GH arcade entries with ports that are NOT in our Arcade/Game export
    # (i.e., excluded by INI scope or by our ports gate)
    gh_not_in_arcade_scope = sorted(gh_keys_with_ports - included_all)


    # Build the clarified 'ports' block for the summary
    summary_ports = {
        # Universe from GH History XML (arcade side)
        "gh_arcade_entries_total": len(gh_ports),
        "gh_arcade_entries_with_ports_total": len(gh_keys_with_ports),

        # Our final export after INI scope + ports gate
        "included_parents_after_ports_gate": len(out_map),

        # Of the included parents, how many have ports on their own GH key
        "included_parents_with_own_ports": {
            "count": parents_with_ports_count,
            "note": "Included parents whose own GH shortname has ≥1 valid port row.",
        },

        # Distinct clones (under included parents) that have ports; full list for traceability
        "included_clones_with_ports": {
            "count": len(clones_with_ports_set),
            "list": sorted(clones_with_ports_set),
            "note": "Clone shortnames (children of included parents) with ≥1 valid GH port row.",
        },

        # GH arcade entries that have ports but are absent from our export (INI scope/filter)
        "gh_arcade_entries_with_ports_excluded_by_ini": {
            "count": len(gh_not_in_arcade_scope),
            "list": gh_not_in_arcade_scope,
            "note": "GH/MAME shortnames with ≥1 valid port row that are not in our Arcade/Game export.",
        },
    }

    # Derived figures (informational)
    parents_included_due_to_clones_only = (
        len(out_map) - parents_with_ports_count
    )


    # --- Parents included due to clone ports only: full list ---
    # A parent is in this bucket if it is included,
    # AND it has NO parent_source in its ports object (i.e., only clones had ports).
    parents_included_due_to_clones_only_list = sorted(
        m for m, rec in out_map.items()
        if not ((rec.get("ports") or {}).get("parent_source"))
    )

    # Optional soft check: length should match the derived count you computed earlier
    if len(parents_included_due_to_clones_only_list) != (
        len(out_map) - parents_with_ports_count
    ):
        log.warning(
            "[ports] parents_included_due_to_clones_only length mismatch: "
            f"list={len(parents_included_due_to_clones_only_list)} "
            f"vs derived={len(out_map) - parents_with_ports_count}"
        )


    summary_ports.setdefault("derived", {})
    summary_ports["derived"].update({
        "parents_included_due_to_clones_only": len(parents_included_due_to_clones_only_list),
        "parents_included_due_to_clones_only_list": parents_included_due_to_clones_only_list,
        "note_parents_included_due_to_clones_only": (
            "Included parents that do not have ports on their own GH key, "
            "but were included because at least one clone has ports."
        ),
    })

    summary_ports["parent_clone_duplicate_ports"] = {
        "systems_count": systems_with_parent_clone_port_dupes,
        "systems_list": sorted(systems_with_parent_clone_port_dupes_list),
        "note": "Systems where at least one port row is identical between the parent GH entry and a clone GH entry (same category).",
        "note_duplicates": "Ports are not de-duplicated; identical parent/clone rows may appear intentionally for audit."
    }


    header_versions = dict(versions)
    header_versions["transformer_version"] = tool_version("transformer")

    summary = {
        "header": {
            "schema_id": SCHEMA_IDS["transform"],
            "schema_version": schema_version(SCHEMA_IDS["transform"]),
            "generated_at": finished_utc,
            "started_utc": started_utc,
            "finished_utc": finished_utc,
            "duration_seconds": duration,
            "versions": header_versions,
        },
        
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
            "parents_without_clones": len(eligible_parents) - parents_with_clones,
            "parents_with_any_media": parents_with_any_media,
            "media_label_counts": media_label_counts_sorted,
            "audio": {
                "machines_reporting_channels": audio_total_with_channels,
                "channel_speaker_mismatches": audio_channel_speaker_mismatch,
                "mismatch_examples": audio_mismatch_examples,
                "machines_requiring_samples": audio_samples_required_count,
            },
        },

        "excluded_parents_by_reason": excluded_reasons,
        "included_flags": included_flags,

        "title_anomaly_counts": title_anomaly_counts,
        "title_anomalies": title_anomalies,

        "title_overrides": {
            "stats": overrides_stats,
            "applied": overrides_applied,
        },

        "ports": summary_ports,

        "notes": {
            "ports_attached": True,
            "export_scope": "Parents are exported only if INI says Arcade/Game AND the parent or any clone has ≥1 valid GH port row (platform present).",
            "filter_rules": {
                "game_status_equals": "game",
                "category_must_include": "Arcade",
                "ignore_coin_op_games": True,
                "ignore_type_for_filter": True,
                "ignore_isbios_isdevice_ismechanical_for_filter": True,
            },
            "title_parsing": {
                "numbered_fields": True,
                "global_version_is_single_string": True,
                "only_top_level_groups": True,
                "nested_preserved_inside": True,
            },
            "clones_list_title_source": "raw MAME 'description' (no overrides)",
            "ignored_media_devices": {
                "total_ignored_entries": ignored_total,
                "unique_ignored": len(ignored_device_counts),
                "top_ignored": ignored_top,
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

    # Soft QA checks (warn-only)
    if parents_with_ports_count > len(out_map):
        log.warning(
            "[ports] parents_with_ports_count > included_parents_after_ports_gate "
            f"({parents_with_ports_count} > {len(out_map)}): check counting logic."
        )

    if not clones_with_ports_set.issubset(included_clones_set):
        extras = sorted(clones_with_ports_set - included_clones_set)[:20]
        log.warning(
            "[ports] Some clones_with_ports are not children of included parents "
            f"(showing up to 20): {extras}"
        )

    if len(gh_keys_with_ports) > len(gh_ports):
        log.warning(
            "[ports] gh_keys_with_ports larger than gh_ports keys "
            f"({len(gh_keys_with_ports)} > {len(gh_ports)}): unexpected."
        )

    # Sanity: 'excluded_by_ini' should be a subset of GH keys
    if not set(summary_ports["gh_arcade_entries_with_ports_excluded_by_ini"]["list"]).issubset(set(gh_keys_with_ports)):
        log.warning("[ports] Excluded-by-INI list contains entries not in gh_keys_with_ports.")


    ok_sum = _write_json(TRANS_SUMMARY_PATH, summary)
    
    save_stamp(stamp_path, current_stamp)
    
    log.info(f"Transformer completed in {duration:.2f}s "
             f"(eligible_parents={len(eligible_parents)}, included={len(out_map)})")
    return bool(ok_out and ok_sum)


if __name__ == "__main__":
    ok = run_transformer(DATA_DIR)
    raise SystemExit(0 if ok else 1)
