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
from typing import Dict, Any, Optional, Set, List, Tuple
import json
import datetime
import time
import re

from config import LOG_LEVEL
from logger import setup_logger, debug_log

log = setup_logger(log_level=LOG_LEVEL)

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")

MAME_MACHINES_PATH = OUTPUT_DIR / "mame_machines.json"
INI_CLASS_PATH     = OUTPUT_DIR / "gh_ini_classifications.json"
PARENT_INDEX_PATH  = OUTPUT_DIR / "mame_parent_index.json"

WIKI_OUT_PATH      = OUTPUT_DIR / "exotica_lit_wiki.json"
TRANS_SUMMARY_PATH = DATA_DIR / "transform_summary.json"


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
    info = mame.get(machine, {})
    if info.get("cloneof"):
        return False
    c = _classify(machine, ini_map)
    return (c["game_status"] == "game") and ("Arcade" in c["category"])

def _build_final_set(eligible_parents: Set[str],
                     parent_index: Dict[str, Any]) -> Set[str]:
    final: Set[str] = set(eligible_parents)
    parents_map: Dict[str, list] = (parent_index or {}).get("parents", {})
    for p in sorted(eligible_parents):
        final.update(parents_map.get(p, []))
    return final

def _machine_title(m: Dict[str, Any], fallback: str) -> str:
    return m.get("description") or m.get("title") or m.get("fullname") or fallback

def _bool(v: Any) -> bool:
    return bool(v) if isinstance(v, (bool, int, str)) else False

def _load_title_overrides(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning(f"Failed to read title overrides {path}: {e}")
        return {}

def _truthy_flag(v) -> bool:
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

def _dedupe_anomalies_preferring_pre_override(anoms: dict) -> dict:
    out = {}
    for cat, items in anoms.items():
        seen = {}
        for it in items:
            key = (it.get("machine"), it.get("example"))
            prev = seen.get(key)
            if prev is None:
                seen[key] = it
            else:
                # prefer items marked pre_override
                if it.get("pre_override") and not prev.get("pre_override"):
                    seen[key] = it
        out[cat] = list(seen.values())
    return out


# ----------------------------
# TITLE PARSING (fixed)
# ----------------------------

_ALNUM = re.compile(r"[A-Za-z0-9]")
_INFIX_RE = re.compile(r"[A-Za-z0-9]\([^()\[\]]+\)[A-Za-z0-9]")

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
    # Build an ordered list of group spans AFTER from_index
    spans = [(s, e) for (s, e, _, _) in groups if s >= from_index]
    spans.sort()
    cursor = from_index
    for (s, e) in spans:
        # outside before this group
        if s > cursor:
            frag = unit[cursor:s].strip()
            if frag:
                tokens.append(_clean_token(frag))
        cursor = e + 1
    # tail after last group
    if cursor < len(unit):
        frag = unit[cursor:].strip()
        if frag:
            tokens.append(_clean_token(frag))
    # drop empties
    return [t for t in tokens if t]

def _clean_token(t: str) -> str:
    """Trim and drop leading/trailing punctuation commonly used as separators."""
    t = t.strip()
    # strip leading separators
    while t and t[0] in "-:,/;()[]":
        t = t[1:].lstrip()
    # strip trailing separators
    while t and t[-1] in "-:,/;()[]":
        t = t[:-1].rstrip()
    # collapse inner whitespace
    t = " ".join(t.split())
    return t

def _find_infix_brackets_no_spaces(s: str) -> bool:
    """Heuristic: bracket group immediately between alnum on both sides."""
    return _INFIX_RE.search(s) is not None

def _find_unbalanced(full: str) -> Tuple[bool, bool]:
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
    # Collect top-level groups (content already normalised)
    groups = _top_level_groups(unit_text)
    # Decide subtitle split space
    first_tr_start = _first_trailing_start(unit_text, groups)
    cut = first_tr_start if first_tr_start is not None else len(unit_text)
    head = unit_text[:cut]
    # Subtitle split on first ' - ' or ':' outside brackets (head has no trailing groups)
    sub_pos = None
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
        # _normalise_inside_group already applied inside _top_level_groups; to detect change,
        # run it again and compare (cheap, deterministic)
        _, changed = _normalise_inside_group(content_raw)
        if changed:
            warn["odd_separator_usage"] = True
            break

    # Outside tokens after first group (if any), without duplicating groups
    outside_tokens: List[str] = []
    if first_tr_start is not None:
        outside_tokens = _split_outside_tokens_after(unit_text, groups, from_index=groups[0][1] + 1)

    # Extract ordered group contents only
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

    # Split into title units
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

    # Build numbered fields
    desc: Dict[str, str] = {}
    for idx in range(len(unit_info)):
        desc[f"title{idx+1}"] = ""
        desc[f"subtitle{idx+1}"] = ""
        desc[f"version{idx+1}"] = ""

    for idx, (base, sub, _, _, _) in enumerate(unit_info, start=1):
        desc[f"title{idx}"] = base
        desc[f"subtitle{idx}"] = sub

    # Per spec: if exactly one (top-level) group in the WHOLE string → it's global_version
    global_parts: List[str] = []
    if total_top_groups == 1:
        for (_, _, groups, outs, _) in unit_info:
            if groups:
                global_parts.append(groups[0])
                # any outside tokens after that group also go to global
                for t in outs:
                    global_parts.append(t)
                break
    else:
        # First group after each unit → version; remaining groups + outside tokens → global
        for idx, (_, _, groups, outs, _) in enumerate(unit_info, start=1):
            if groups:
                desc[f"version{idx}"] = groups[0]
                for extra in groups[1:]:
                    global_parts.append(extra)
            for t in outs:
                global_parts.append(t)

    # Join global parts into one string (keep order, drop empties)
    desc["global_version"] = ", ".join(p for p in global_parts if p)

    return desc, anomalies


# ----------------------------
# Main transform
# ----------------------------

def run_transformer(data_dir: Path = DATA_DIR) -> bool:
    started_utc = datetime.datetime.utcnow().isoformat() + "Z"
    t0 = time.perf_counter()

    overrides = _load_title_overrides(DATA_DIR / "title_overrides.json")

    # Track usage for the summary
    overrides_applied: list[dict[str, str]] = []
    overrides_stats = {
        "configured": len(overrides),  # total entries in title_overrides.json
        "eligible": 0,                 # overrides where condition was met (see below)
        "applied": 0                   # overrides we actually used (description replaced)
    }

    # Remember path and whether we actually loaded any overrides
    overrides_path = DATA_DIR / "title_overrides.json"
    have_overrides = isinstance(overrides, dict) and bool(overrides)

    mame = _read_json(MAME_MACHINES_PATH)
    ini_map = _read_json(INI_CLASS_PATH)
    parent_index = _read_json(PARENT_INDEX_PATH)
    if not isinstance(mame, dict) or not isinstance(ini_map, dict) or not isinstance(parent_index, dict):
        log.error("Missing or invalid inputs; aborting transform.")
        return False

    all_names = sorted(mame.keys())
    eligible_parents: Set[str] = {n for n in all_names if _is_eligible_parent(n, mame, ini_map)}
    final_names: Set[str] = _build_final_set(eligible_parents, parent_index)

    out_map: Dict[str, Dict[str, Any]] = {}

    excluded_reasons = {"not_game": 0, "not_arcade": 0, "unknown_classification": 0}
    included_flags = {"isbios": 0, "isdevice": 0, "ismechanical": 0}
    clones_included_unknown_class = 0
    missing_in_mame: List[str] = []

    title_anomalies: Dict[str, List[Dict[str, str]]] = {
        "unbalanced_round_brackets": [],
        "unbalanced_square_brackets": [],
        "infix_brackets_no_spaces": [],
        "ambiguous_trailing_tokens": [],
        "odd_separator_usage": [],
    }

    # Parent exclusion reasons (for info)
    for name in all_names:
        if mame[name].get("cloneof"):
            continue
        c = _classify(name, ini_map)
        if c["game_status"] != "game":
            excluded_reasons["not_game"] += 1
        elif "Arcade" not in c["category"]:
            excluded_reasons["not_arcade"] += 1
        elif c["game_status"] == "unknown" or c["category"] == ["unknown"]:
            excluded_reasons["unknown_classification"] += 1

    for name in sorted(final_names):
        minfo = mame.get(name)
        if not minfo:
            missing_in_mame.append(name); continue

        cls = _classify(name, ini_map)

        #if _bool(minfo.get("isbios")):       included_flags["isbios"] += 1
        #if _bool(minfo.get("isdevice")):     included_flags["isdevice"] += 1
        #if _bool(minfo.get("ismechanical")): included_flags["ismechanical"] += 1        
        if _truthy_flag(minfo.get("isbios")):       included_flags["isbios"] += 1
        if _truthy_flag(minfo.get("isdevice")):     included_flags["isdevice"] += 1
        if _truthy_flag(minfo.get("ismechanical")): included_flags["ismechanical"] += 1
        
        if name in (parent_index.get("child_to_parent") or {}) and (
            cls["game_status"] == "unknown" or cls.get("category") == ["unknown"]
        ):
            clones_included_unknown_class += 1


        raw_desc_original = _machine_title(minfo, name)

        # 2a) collect anomalies on the ORIGINAL string
        _, pre_anoms = _parse_description(raw_desc_original)
        for k, lst in pre_anoms.items():
            for item in lst:
                item["machine"] = name
                item["pre_override"] = True
            title_anomalies[k].extend(lst)

        # 2b) decide/apply override (and count eligible/applied)
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

        # 2c) parse the (possibly overridden) title BUT ignore anomalies now
        desc_fields, _ = _parse_description(raw_desc)


        #raw_desc = _machine_title(minfo, name)
        desc_fields, anomalies = _parse_description(raw_desc)
        for k, lst in anomalies.items():
            if lst:
                for item in lst:
                    item["machine"] = name
                title_anomalies[k].extend(lst)


        record = {
            "machine": name,
            # Parsed description only (no raw MAME title in wiki output)
            "description": desc_fields,
            "year": minfo.get("year") if minfo.get("year") not in ("", None) else None,
            "manufacturer": minfo.get("manufacturer") if minfo.get("manufacturer") not in ("", None) else None,
            "is_parent": False if minfo.get("cloneof") else True,
            "clone_of": minfo.get("cloneof") or None,
            # Classifications
            "game_status": cls["game_status"],
            "category": cls["category"],
            "type": cls["type"],
            # MAME flags (report-only)
            "isbios": _truthy_flag(minfo.get("isbios")),
            "isdevice": _truthy_flag(minfo.get("isdevice")),
            "ismechanical": _truthy_flag(minfo.get("ismechanical")),
            "requires_samples": _truthy_flag(minfo.get("requires_samples")),            
            #"isbios": _bool(minfo.get("isbios")),
            #"isdevice": _bool(minfo.get("isdevice")),
            #"ismechanical": _bool(minfo.get("ismechanical")),
            #"requires_samples": _bool(minfo.get("requires_samples")),
        }
        out_map[name] = record

    ok_out = _write_json(WIKI_OUT_PATH, out_map)

    parents_total = sum(1 for v in mame.values() if not v.get("cloneof"))
    clones_total = sum(1 for v in mame.values() if v.get("cloneof"))

    mame_sum = _read_json(DATA_DIR / "mame_parsing_summary.json") or {}
    hist_sum = _read_json(DATA_DIR / "history_parsing_summary.json") or {}
    ini_sum  = _read_json(DATA_DIR / "ini_parsing_summary.json") or {}
    versions = {
        "mame_build": (mame_sum.get("mame") or {}).get("build"),
        "history_version": (hist_sum.get("history") or {}).get("version"),
        "history_date": (hist_sum.get("history") or {}).get("date"),
        "ini_generated_at": (ini_sum.get("ini") or {}).get("generated_at"),
    }

    finished_utc = datetime.datetime.utcnow().isoformat() + "Z"
    duration = round(time.perf_counter() - t0, 3)

    inputs_map = {
        "mame_machines": str(MAME_MACHINES_PATH).replace("\\", "/"),
        "ini_classifications": str(INI_CLASS_PATH).replace("\\", "/"),
        "mame_parent_index": str(PARENT_INDEX_PATH).replace("\\", "/"),
    }
    if have_overrides:
        inputs_map["title_overrides"] = str(overrides_path).replace("\\", "/")

    title_anomalies = _dedupe_anomalies_preferring_pre_override(title_anomalies)

    # Count anomalies for quick scanning (after any de-dupe)
    title_anomaly_counts = {k: len(v) for k, v in title_anomalies.items()}

    summary = {
        "transformer_schema": "0.3",
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "duration_seconds": duration,
        "inputs": inputs_map,
        "versions": versions,
        "counts": {
            "mame_total": len(mame),
            "parents_total": parents_total,
            "clones_total": clones_total,
            "eligible_parents": len(eligible_parents),
            "final_included": len(out_map),
            "clones_included_unknown_classification": clones_included_unknown_class,
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
            }
        },
        "errors": [] if ok_out and not missing_in_mame else (
            [{"missing_in_mame": missing_in_mame}] if missing_in_mame else []
        ),
    }

    ok_sum = _write_json(TRANS_SUMMARY_PATH, summary)
    log.info(f"Transformer completed in {duration:.2f}s "
             f"(eligible_parents={len(eligible_parents)}, included={len(out_map)})")
    return bool(ok_out and ok_sum)


if __name__ == "__main__":
    ok = run_transformer(DATA_DIR)
    raise SystemExit(0 if ok else 1)
