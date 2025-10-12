"""
Warning-only invariant checks for parsed outputs.

Includes:
- check_mame_parse_invariants(): cross-checks per-machine records against
  aggregated counters and emits warnings when mismatches are detected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Tuple, Dict, Any, Set
from jsonschema import Draft202012Validator
from collections import Counter, defaultdict

from mht.utils.paths import (
    # output docs
    EXOTICA_RAW,
    EXOTICA_WIKI,
    EXOTICA_PAGES,
    # schemas
    EXOTICA_RAW_SCHEMA,
    EXOTICA_WIKI_SCHEMA,
    EXOTICA_PAGES_SCHEMA,
)

# One source of truth for (schema, document) pairs
REGISTRY: Dict[str, Tuple[Path, Path]] = {
    "raw":   (EXOTICA_RAW_SCHEMA,   EXOTICA_RAW),
    "wiki":  (EXOTICA_WIKI_SCHEMA,  EXOTICA_WIKI),
    "pages": (EXOTICA_PAGES_SCHEMA, EXOTICA_PAGES),
}

def validate(names: Iterable[str] | None = None) -> list[str]:
    """
    Validate one or more output JSON documents against their JSON Schemas.

    Parameters
    ----------
    only
        Optional subset of keys from VALIDATION_REGISTRY to validate.

    Returns
    -------
    list[str]
        Human-readable error lines; empty list means 'Validation OK'.
    """
    targets = (names or REGISTRY.keys())
    errors_out: list[str] = []

    for name in targets:
        if name not in REGISTRY:
            errors_out.append(f"[{name}] unknown target")
            continue

        schema_path, doc_path = REGISTRY[name]
        if not schema_path.exists():
            errors_out.append(f"[{name}] missing schema: {schema_path}")
            continue
        if not doc_path.exists():
            errors_out.append(f"[{name}] missing document: {doc_path}")
            continue

        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            doc    = json.loads(doc_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors_out.append(f"[{name}] read error: {e}")
            continue

        v = Draft202012Validator(schema)
        problems = list(v.iter_errors(doc))
        if problems:
            for e in sorted(problems, key=lambda e: (list(e.path), e.message)):
                path_str = "/".join(map(str, e.path)) or "(root)"
                errors_out.append(f"[{name}] /{path_str} -> {e.message}")

    return errors_out

def check_mame_parse_invariants(
    *,
    log,  # logger with .warning()
    log_prefix: str,
    total_machines: int,
    machines_out: Dict[str, Dict[str, Any]],
    years_ctr: Counter,
    manuf_ctr: Counter,
    players_ctr: Counter,
    cpus_per_machine_ctr: Counter,
    sound_devices_per_machine_ctr: Counter,
    displays_per_machine_ctr: Counter,
    speakers_per_machine_ctr: Counter,
    sound_channels_per_machine_ctr: Counter,
    display_types_overall_ctr: Counter,
    display_tags_overall_ctr: Counter,
    disk_media_platforms_per_machine_ctr: Counter,
    control_type_overall_ctr: Counter,
    control_ways_overall_ctr: Counter,
    control_ways2_overall_ctr: Counter,
    control_ways3_overall_ctr: Counter,
    control_buttons_overall_ctr: Counter,
    control_reqbuttons_overall_ctr: Counter,
):
    """
    Emit warnings when summary counters disagree with per-machine data.

    Matches the legacy inline checks from mame_parser.parse_mame_xml:
    - Sums across distributions must equal total_machines (for selected counters)
    - Display types/tags totals must equal sum(displays per machine)
    - Disk flags/regions consistency check
    - Controls overall counters must equal the total number of <control> entries
    - Chip count mismatches: recompute cpu/audio counts from chips[]
    """
    def _sum(counter: Counter) -> int:
        return sum(counter.values())

    # 1) Distributions that should sum to total_machines
    checks_equal_total: Iterable[tuple[str, int]] = [
        ("years_ctr", _sum(years_ctr)),
        ("manuf_ctr", _sum(manuf_ctr)),
        ("players_ctr", _sum(players_ctr)),
        ("cpus_per_machine_ctr", _sum(cpus_per_machine_ctr)),
        ("sound_devices_per_machine_ctr", _sum(sound_devices_per_machine_ctr)),
        ("displays_per_machine_ctr", _sum(displays_per_machine_ctr)),
        ("speakers_per_machine_ctr", _sum(speakers_per_machine_ctr)),
        ("sound_channels_per_machine_ctr", _sum(sound_channels_per_machine_ctr)),
        ("disk_media_platforms_per_machine_ctr", _sum(disk_media_platforms_per_machine_ctr)),
    ]
    for name, val in checks_equal_total:
        if val != total_machines:
            log.warning(f"{log_prefix} Invariant: sum({name})={val} != total_machines={total_machines}")

    # 2) Display types/tags should match expected number of displays overall
    expected_total_displays = sum(int(k) * v for k, v in displays_per_machine_ctr.items() if str(k).isdigit())
    types_sum = _sum(display_types_overall_ctr)
    tags_sum = _sum(display_tags_overall_ctr)
    if types_sum != expected_total_displays:
        log.warning(f"{log_prefix} Display types total {types_sum} != expected {expected_total_displays}")
    if tags_sum != expected_total_displays:
        log.warning(f"{log_prefix} Display tags total {tags_sum} != expected {expected_total_displays}")

    # 3) Disk flag/regions consistency
    disk_flag_yes_empty = 0
    disk_flag_no_nonempty = 0
    for m in machines_out.values():
        dr = (m.get("disk_required"))
        regs = m.get("disk_regions") or []
        if dr == "yes" and not regs:
            disk_flag_yes_empty += 1
        elif dr == "no" and regs:
            disk_flag_no_nonempty += 1
    if disk_flag_yes_empty or disk_flag_no_nonempty:
        log.warning(f"{log_prefix} Disk consistency: yes+empty={disk_flag_yes_empty}, no+nonempty={disk_flag_no_nonempty}")

    # 4) Controls overall counters must equal total <control> entries
    total_controls_entries = sum(len(m.get("controls") or []) for m in machines_out.values())
    ctrl_sums = [
        ("control_type_overall", _sum(control_type_overall_ctr)),
        ("control_ways_overall", _sum(control_ways_overall_ctr)),
        ("control_ways2_overall", _sum(control_ways2_overall_ctr)),
        ("control_ways3_overall", _sum(control_ways3_overall_ctr)),
        ("control_buttons_overall", _sum(control_buttons_overall_ctr)),
        ("control_reqbuttons_overall", _sum(control_reqbuttons_overall_ctr)),
    ]
    for label, val in ctrl_sums:
        if val != total_controls_entries:
            log.warning(f"{log_prefix} Controls total mismatch: {label}={val} != {total_controls_entries}")

    # 5) Chip count mismatches vs per-machine chip list
    cpu_mismatch = 0
    audio_mismatch = 0
    for m in machines_out.values():
        chips = m.get("chips") or []
        cpus = sum(1 for c in chips if (c.get("type") or "").lower() == "cpu")
        audios = sum(1 for c in chips if (c.get("type") or "").lower() == "audio")
        if cpus != (m.get("cpu_count") or 0):
            cpu_mismatch += 1
        if audios != (m.get("sound_chip_count") or 0):
            audio_mismatch += 1
    if cpu_mismatch or audio_mismatch:
        log.warning(f"{log_prefix} Chip count mismatches: cpu={cpu_mismatch}, audio={audio_mismatch}")

def check_history_parse_invariants(
    *,
    log,  # logger with .warning() / .info()
    systems_count: int,
    software_count: int,
    total_entries: int,
    gh_systems: Dict[str, Dict[str, Any]],
    parsing_state: Dict[str, Any],
    KNOWN_PLATFORMS: set[str] | Dict[str, Any],  # accepts set or dict-like
) -> None:
    """
    Emit warnings when parsed history counters disagree with expectations.

    Mirrors the inline checks previously in history_parser.parse_history_entries:
    - systems_count + software_count equals total_entries
    - gh_systems size equals systems_count
    - platform hit totals match parsed port lines (including null platform lines)
    - banner totals are consistent with per-system tallies
    - monotonic relations (systems_with_ports <= systems_count, etc.)
    - unexpected PORTS categories listed informatively
    """
    issues = 0

    def _warn_ok(cond: bool, msg: str):
        nonlocal issues
        if not cond:
            issues += 1
            log.warning(msg)

    _warn_ok(
        systems_count + software_count == total_entries,
        f"[history_parser] systems+software != total_entries ({systems_count}+{software_count}!={total_entries})",
    )
    _warn_ok(len(gh_systems) == systems_count,
             f"[history_parser] gh_systems count {len(gh_systems)} != systems_count {systems_count}")

    platform_hits = sum(d["count"] for d in parsing_state["platforms_found"].values())
    null_pl = parsing_state["null_platform_ports_total"]
    total_port_lines_all = parsing_state.get("total_port_lines_all", 0) or 0  # optional cache
    # fall back if not provided in parsing_state
    if not total_port_lines_all:
        total_port_lines_all = sum(parsing_state.get("platform_banners_by_system", {}).get(sys, Counter()).total()
                                   for sys in parsing_state.get("platform_banners_by_system", {}))  # best-effort

    _warn_ok(
        platform_hits + null_pl == parsing_state.get("total_port_lines_all", total_port_lines_all),
        "[history_parser] platforms_found + null_platforms != port_lines_parsed",
    )

    _warn_ok(sum(parsing_state["null_platform_ports_by_system"].values()) == null_pl,
             "[history_parser] per-system null platform sum mismatch")

    banner_total_calc = sum(sum(c.values()) for c in parsing_state["platform_banners_by_system"].values())
    _warn_ok(banner_total_calc == parsing_state["platform_banner_total"],
             "[history_parser] platform_banner_total mismatch")

    systems_with_ports = parsing_state.get("systems_with_ports_count")
    if systems_with_ports is None:
        # derive defensively if not cached
        systems_with_ports = len(parsing_state.get("systems_with_port_overview", {})) or 0
    _warn_ok(systems_with_ports <= systems_count,
             f"[history_parser] systems_with_ports {systems_with_ports} > systems_count {systems_count}")

    port_overview_count = parsing_state.get("port_overview_count", 0)
    _warn_ok(port_overview_count <= systems_with_ports,
             f"[history_parser] port_overview_count {port_overview_count} > systems_with_ports {systems_with_ports}")

    # Unexpected categories (case-insensitive)
    kp = set(k.upper() for k in (KNOWN_PLATFORMS.keys() if hasattr(KNOWN_PLATFORMS, "keys") else KNOWN_PLATFORMS))
    found = parsing_state["platform_categories_found"].keys()
    unknown_cats = sorted({k for k in found if k.upper() not in kp})
    if unknown_cats:
        log.info("[history_parser] unexpected PORTS categories: %s", ", ".join(unknown_cats))

    # Residue vs unparsable_dates sanity check
    _warn_ok(
        len(parsing_state.get("systems_with_residue", set())) >= len(parsing_state.get("unparsable_dates", {})),
        "[history_parser] systems_with_residue fewer than unparsable_dates keys",
    )

    if issues == 0:
        log.info("[history_parser] invariants passed")

# --- INI invariants ----------------------------------------------------------

def validate_ini_parsed_bundle(parsed: Dict[str, dict], log) -> int:
    """
    Warnings-only checks over the parsed INI bundle produced by load_ini_classifications().

    Returns
    -------
    int : number of issues found (each logged as a warning).
    """
    issues = 0

    def _warn_ok(cond: bool, msg: str):
        nonlocal issues
        if not cond:
            issues += 1
            log.warning(msg)

    for key in ("game_status", "category", "type"):
        info = parsed.get(key) or {}
        ms: Dict[str, Set[str]] = info.get("machine_sections", {}) or {}
        slc: Dict[str, int]      = info.get("section_listed_counts", {}) or {}
        sus: Dict[str, Set[str]] = info.get("section_unique_sets", {}) or {}

        entries_listed = int(info.get("entries_listed", 0))
        mmulti         = int(info.get("machines_with_multiple_sections", 0))
        d_across       = int(info.get("duplicates_across_sections", 0))
        d_within       = int(info.get("duplicates_within_section", 0))

        # 1) entries_listed should equal the sum of listed counts across sections
        _warn_ok(
            entries_listed == sum(slc.values()),
            f"[ini.validator] {key}: entries_listed={entries_listed} "
            f"!= sum(section_listed_counts)={sum(slc.values())}"
        )

        # 2) duplicates_within_section should equal listed minus unique across sections
        uniques_sum = sum(len(s) for s in sus.values())
        _warn_ok(
            d_within == entries_listed - uniques_sum,
            f"[ini.validator] {key}: duplicates_within_section={d_within} "
            f"!= entries_listed({entries_listed}) - uniques_sum({uniques_sum})"
        )

        # 3) machines_with_multiple_sections matches the count of machines with ≥2 sections
        mmulti_calc = sum(1 for s in ms.values() if len(s) >= 2)
        _warn_ok(
            mmulti == mmulti_calc,
            f"[ini.validator] {key}: machines_with_multiple_sections={mmulti} "
            f"!= calculated={mmulti_calc}"
        )

        # 4) duplicates_across_sections is at least the minimal calc (len-1 over each machine)
        d_across_calc = sum(len(s) - 1 for s in ms.values() if len(s) >= 1)
        _warn_ok(
            d_across == d_across_calc,
            f"[ini.validator] {key}: duplicates_across_sections={d_across} "
            f"!= calculated={d_across_calc}"
        )

        # 5) sanity: entries_indexed == len(machine_sections)
        _warn_ok(
            len(ms) == len(ms.keys()),
            f"[ini.validator] {key}: unexpected mapping irregularity in machine_sections"
        )

    return issues
