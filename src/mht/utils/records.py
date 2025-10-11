"""
Filename: utils/records.py
Author: XtC

Builds the per-parent "record" (the rich object that later projects to wiki/raw),
and returns telemetry to help the transformer accumulate summary stats.

This keeps the heavy lifting (chips/displays/controls/ports/roms/title fields)
out of transformer.py while preserving identical behaviour.
"""

from __future__ import annotations

from typing import Dict, Any, Tuple, List, Set, Optional
from pathlib import Path

from mht.utils.strings import format_manufacturers_for_wiki
from mht.utils.roms import format_rom_block
from mht.utils.chips import (
    build_chips_section,
    render_chips_display,
    sum_device_speakers,
    _has_samples_flag,
)
from mht.utils.displays import (
    build_displays_section,
    displays_section_to_display,
)
from mht.utils.controls import (
    build_controls_section,
    controls_section_to_display,
)
from mht.utils.ports import (
    build_ports_for_parent,
    gh_ids_from_ports_obj,
    has_parent_clone_duplicate_ports,
)
from mht.utils.media import (
    normalise_device_to_media,
    normalise_device_list_to_media,
)
from mht.utils.selection import classify as _classify
from mht.utils.booleans import truthy_flag as _truthy_flag

# --- small helpers kept here to avoid reintroducing transformer-level noise ---

def _raw_mame_title(minfo: Dict[str, Any], fallback: str) -> str:
    return (
        minfo.get("description")
        or minfo.get("title")
        or minfo.get("fullname")
        or fallback
    )

def _mame_titles_for_parent(parent_name: str,
                            mame: Dict[str, Any],
                            parent_index: Dict[str, Any]) -> List[dict]:
    out: List[dict] = []
    pinfo = mame.get(parent_name, {})
    out.append({
        "role": "parent",
        "machine": parent_name,
        "title": _raw_mame_title(pinfo, parent_name),
        "year": pinfo.get("year"),
    })
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

# --- public API ---

def build_parent_record(
    *,
    parent_name: str,
    mame: Dict[str, Any],
    ini_map: Dict[str, Dict[str, Any]],
    parent_index: Dict[str, Any],
    gh_ports: Dict[str, Any],
    # description fields + wiki name are produced earlier by title parsing
    desc_fields: Dict[str, str],
    wiki_page_name: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Assemble the full per-parent record used by the raw and wiki projections.

    The record includes manufacturers, ROM/media summary, chips/displays/controls
    sections, titles, PORTS (merged with clone provenance), GH IDs, and flags.
    Telemetry returns counters/sets used for run-level summaries.
    """
    minfo = mame.get(parent_name, {}) or {}

    # ---- manufacturer display (split ‘/’ outside parens, join with ‘&’) ----
    manufacturer_display = format_manufacturers_for_wiki(minfo.get("manufacturer") or "")

    # ---- ROM/media block ----------------------------------------------------
    rom_count       = int(minfo.get("rom_count") or 0)
    rom_bytes_total = int(minfo.get("rom_bytes_total") or 0)
    disk_required   = minfo.get("disk_required")
    disk_regions    = minfo.get("disk_regions")

    roms_display = format_rom_block(
        rom_count=rom_count,
        rom_bytes_total=rom_bytes_total,
        disk_required=disk_required,
        disk_regions=disk_regions,
    )

    # Media telemetry (for transformer-wide stats)
    media_labels_for_counts: Set[str] = set()
    ignored_devices: Dict[str, int] = {}
    parents_with_any_media = False
    if (str(disk_required or "").lower() == "yes"):
        labels_for_counts = normalise_device_list_to_media(disk_regions)
        if labels_for_counts:
            parents_with_any_media = True
            for lab in dict.fromkeys(labels_for_counts):
                media_labels_for_counts.add(lab)
        # Note: record any device strings that didn't map to a known label
        seq = disk_regions if isinstance(disk_regions, (list, tuple)) else (
            [disk_regions] if disk_regions else []
        )
        for raw in seq:
            if normalise_device_to_media(str(raw)) is None:
                key = str(raw)
                ignored_devices[key] = ignored_devices.get(key, 0) + 1

    # ---- Chips / Displays / Controls ---------------------------------------
    chips_section = build_chips_section(
        minfo.get("chips"),
        minfo.get("sound_channels"),
        minfo.get("device_ref"),
    )
    displays_section = build_displays_section(
        minfo.get("displays"),
        minfo.get("display_count"),
    )
    controls_section = build_controls_section(
        minfo.get("players"),
        minfo.get("controls"),
    )

    displays_display = displays_section_to_display(displays_section)
    controls_display = controls_section_to_display(controls_section)

    # Audio telemetry (channels vs speakers + samples flag)
    reported_channels = minfo.get("sound_channels")
    try:
        chn = int(reported_channels) if reported_channels not in (None, "") else 0
    except Exception:
        chn = 0
    speaker_sum = sum_device_speakers(minfo.get("device_ref"))
    samples_required = _has_samples_flag(minfo.get("device_ref"))

    chips_disp = render_chips_display(
        chips_section,
        requires_samples=_truthy_flag(minfo.get("requires_samples")),
        sound_channels=(int(reported_channels) if reported_channels not in (None, "") else None),
        speaker_count=(int(speaker_sum) if speaker_sum not in (None, "") else None),
    )
    cpus_lines   = list(chips_disp.get("cpus") or [])
    audio_lines  = list(chips_disp.get("audio_chips") or [])
    cpu_hdr      = f"{'CPU' if len(cpus_lines) == 1 else 'CPUs'}:"
    audio_hdr    = f"{'Audio Chip' if len(audio_lines) == 1 else 'Audio Chips'}:"
    chips_display_block = "\n".join([cpu_hdr, *cpus_lines, audio_hdr, *audio_lines])

    # ---- Ports (parent + clones) -------------------------------------------
    parents_map: Dict[str, List[str]] = (parent_index or {}).get("parents", {}) or {}
    ports_obj, clones_with_ports, parent_has_ports = build_ports_for_parent(
        parent_name, parents_map, gh_ports
    )
    if ports_obj is None:
        # No valid ports at all (parent nor clones) — upstream transformer filters these out.
        return {}, {
            "media_labels_for_counts": set(),
            "ignored_devices": {},
            "parents_with_any_media": parents_with_any_media,
            "audio_channels_reported": chn,
            "speaker_sum": speaker_sum,
            "samples_required": samples_required,
            "parent_has_ports": False,
            "clones_with_ports": set(),
            "has_parent_clone_port_dupes": False,
        }

    if not isinstance(ports_obj.get("clone_sources"), list):
        ports_obj["clone_sources"] = []
    if not isinstance(ports_obj.get("parent_source"), dict):
        ports_obj["parent_source"] = {}

    gh_ids = gh_ids_from_ports_obj(ports_obj)
    has_dupes = has_parent_clone_duplicate_ports(ports_obj)

    # ---- MAME titles (parent + clones list) --------------------------------
    mame_titles = _mame_titles_for_parent(parent_name, mame, parent_index)

    # ---- Classification (from INI) --------------------------------------------
    cls = _classify(parent_name, ini_map)  # safe fallback to "unknown"
    game_status = cls["game_status"]
    category    = cls["category"]
    type_       = cls["type"]

    # ---- Classification (leave unchanged; transformer passes it in or sets later) ---
    # We only set fields here that the transformer already populated before.
    # (Transformer still computes eligibility/classification separately.)

    record: Dict[str, Any] = {
        "wiki_page_name": wiki_page_name,
        "description": desc_fields,
        "year": minfo.get("year") if minfo.get("year") not in ("", None) else None,
        "manufacturer": manufacturer_display if manufacturer_display else None,
        "roms_display": roms_display,
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
        # >>> add these <<<
        "game_status": game_status,
        "category":    category,
        "type":        type_,        
        "isbios": _truthy_flag(minfo.get("isbios")),
        "isdevice": _truthy_flag(minfo.get("isdevice")),
        "ismechanical": _truthy_flag(minfo.get("ismechanical")),
        "requires_samples": _truthy_flag(minfo.get("requires_samples")),
        "mame_titles": mame_titles,
        "ports": ports_obj,
        "gh_ids": gh_ids,
    }

    telemetry = {
        "media_labels_for_counts": media_labels_for_counts,
        "ignored_devices": ignored_devices,
        "parents_with_any_media": parents_with_any_media,
        "audio_channels_reported": chn,
        "speaker_sum": speaker_sum,
        "samples_required": samples_required,
        "parent_has_ports": parent_has_ports,
        "clones_with_ports": clones_with_ports,
        "has_parent_clone_port_dupes": has_dupes,
    }

    return record, telemetry

def project_for_wiki(rec: dict) -> dict:
    out = {}
    if rec.get("wiki_page_name"): out["wiki_page_name"] = rec["wiki_page_name"]
    out["wiki_redirects"] = rec.get("wiki_redirects", [])
    if rec.get("year") is not None: out["year"] = rec["year"]
    if rec.get("manufacturer") is not None: out["manufacturer"] = rec["manufacturer"]
    if rec.get("mame_titles_display"):
        out["mame_titles_display"] = rec["mame_titles_display"]
    for k in ("roms_display", "chips_display", "displays_display", "controls_display"):
        if rec.get(k): out[k] = rec[k]
    if rec.get("ports_display"):
        out["ports_display"] = rec["ports_display"]
    if rec.get("gh_ids"):
        out["gh_ids"] = rec["gh_ids"]
    return out

def project_for_raw(machine: str, rec: dict) -> dict:
    out = {}
    out["machine"] = machine
    if rec.get("wiki_page_name"): out["wiki_page_name"] = rec["wiki_page_name"]
    out["wiki_redirects"] = rec.get("wiki_redirects", [])
    if rec.get("mame_titles"): out["mame_titles"] = rec["mame_titles"]
    if rec.get("description"): out["description"] = rec["description"]
    if rec.get("year") is not None: out["year"] = rec["year"]
    if rec.get("manufacturer") is not None: out["manufacturer"] = rec["manufacturer"]
    for k in ("rom_count", "rom_bytes_total", "disk_required", "disk_regions"):
        if k in rec: out[k] = rec[k]
    if rec.get("chips"): out["chips"] = rec["chips"]
    if rec.get("displays"): out["displays"] = rec["displays"]
    if rec.get("controls"): out["controls"] = rec["controls"]
    if rec.get("ports"): out["ports"] = rec["ports"]
    for k in ("game_status", "category", "type", "isbios", "isdevice", "ismechanical", "requires_samples"):
        if k in rec: out[k] = rec[k]
    if rec.get("gh_ids"): out["gh_ids"] = rec["gh_ids"]
    return out

def build_mame_machine_record(
    *,
    description: Optional[str],
    sourcefile: str,
    cloneof: Optional[str],
    isbios: str,
    isdevice: str,
    ismechanical: str,
    year: str,
    manufacturer: str,
    rom_count: int,
    rom_bytes_total: int,
    disk_required: str,
    disk_regions: List[str],
    disk_media_platforms_count: int,
    cpu_count: int,
    sound_chip_count: int,
    chips: List[Dict[str, Any]],
    sound_channels: Optional[int],
    device_ref_summary: Dict[str, Any],
    sampleof: str,
    display_count: int,
    displays: List[Dict[str, Any]],
    players_value: Optional[int],
    controls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Assemble the per-machine record dict for MAME parsing.

    Behaviour is identical to the previous inline construction in mame_parser:
    - Leaves `description` as-is (may be None; text-field normalisation handled elsewhere).
    - Forces `rom_bytes_total` to 0 when `rom_count == 0`.
    - Wraps device_ref_summary as a single-element list under 'device_ref'.
    """
    return {
        "description": description,
        "sourcefile": sourcefile,
        "cloneof": cloneof,
        "isbios": isbios,
        "isdevice": isdevice,
        "ismechanical": ismechanical,
        "year": year,
        "manufacturer": manufacturer,
        "rom_count": rom_count,
        "rom_bytes_total": rom_bytes_total if rom_count else 0,
        "disk_required": disk_required,
        "disk_regions": disk_regions,
        "disk_media_platforms_count": disk_media_platforms_count,
        "cpu_count": cpu_count,
        "sound_chip_count": sound_chip_count,
        "chips": chips,
        "sound_channels": sound_channels,
        "device_ref": [device_ref_summary],
        "sampleof": sampleof,
        "display_count": display_count,
        "displays": displays,
        "players": players_value,
        "controls": controls,
    }

def build_history_system_record(
    *,
    gh_id: Optional[int] = None,
    aliases: List[str] | None = None,
    port_overview: str = "",
    ports: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Assemble the per-system record for history parsing.
    Shape identical to previous inline dict in history_parser.
    """
    return {
        "gh_id": gh_id,
        "aliases": aliases or [],
        "port_overview": port_overview,
        "ports": ports or {},
    }

def build_history_systems_sorted(gh_systems: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a case-insensitively sorted mapping of system name -> record.
    Matches the previous comprehension in history_parser.
    """
    return {k: gh_systems[k] for k in sorted(gh_systems.keys(), key=str.lower)}
