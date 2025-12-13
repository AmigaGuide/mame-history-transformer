from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, abort, render_template, request

from mht.utils.config import WEB_PREVIEW_PORT, WEB_PREVIEW_AUTO_OPEN
from mht.utils.logger import setup_logger
from mht.utils.paths import (
    exotica_wiki_path,
    mame_machines_path,
    transform_summary_path,
    gh_system_trivia_path,
    active_version,
    outputs_dir,
)

log = setup_logger(__name__)

# ----------------------------------------------------------------------------
# Optional summary path helpers (fallbacks if paths module lacks them)
# ----------------------------------------------------------------------------

try:
    from mht.utils.paths import (  # type: ignore
        mame_parsing_summary_path,
        history_parsing_summary_path,
        ini_parsing_summary_path,
    )
except Exception:  # noqa: BLE001

    def _summaries_dir() -> Path:
        # outputs_dir() is expected to be: data/releases/<ver>/outputs
        # so summaries are likely: data/releases/<ver>/summaries
        return outputs_dir().parent / "summaries"

    def mame_parsing_summary_path() -> Path:  # type: ignore[misc]
        return _summaries_dir() / "mame_parsing_summary.json"

    def history_parsing_summary_path() -> Path:  # type: ignore[misc]
        return _summaries_dir() / "history_parsing_summary.json"

    def ini_parsing_summary_path() -> Path:  # type: ignore[misc]
        return _summaries_dir() / "ini_parsing_summary.json"


# ----------------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------------

@dataclass
class PreviewData:
    wiki_doc: Dict[str, Any]
    wiki_games: Dict[str, Dict[str, Any]]
    trivia_by_machine: Dict[str, Any]
    mame_machines: Dict[str, Dict[str, Any]]

    # Summaries
    mame_summary: Dict[str, Any]
    history_summary: Dict[str, Any]
    ini_summary: Dict[str, Any]
    transform_summary: Dict[str, Any]

    machine_order: List[str]


# ----------------------------------------------------------------------------
# Helpers to locate and load JSON
# ----------------------------------------------------------------------------

def _load_json(path: Path, label: str) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found at {path.as_posix()}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{label} at {path.as_posix()} is not a JSON object.")
        return data
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to load {label} from {path.as_posix()}: {exc}") from exc


def _find_trivia_path() -> Path:
    """Return the trivia path for the active release."""
    return gh_system_trivia_path()


def _normalise_trivia_root(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trivia JSON may be shaped as:
      { "<machine>": {...}, ... }
    or:
      { "systems": { "<machine>": {...}, ... } }
    or:
      { "games": { "<machine>": {...}, ... } }

    This function returns the inner mapping keyed by machine name.
    """
    if "systems" in doc and isinstance(doc["systems"], dict):
        return doc["systems"]
    if "games" in doc and isinstance(doc["games"], dict):
        return doc["games"]
    return doc


def _load_preview_data() -> PreviewData:
    """
    Load all JSON artefacts required for the preview server.
    Raises clear exceptions if anything is missing.
    """
    wiki_path = exotica_wiki_path()
    mame_path = mame_machines_path()
    trivia_path = _find_trivia_path()

    # Summaries
    mame_sum_path = mame_parsing_summary_path()
    hist_sum_path = history_parsing_summary_path()
    ini_sum_path = ini_parsing_summary_path()
    xform_sum_path = transform_summary_path()

    log.info("Web preview loading artefacts from active release %s", active_version())
    log.info("  wiki:      %s", wiki_path.as_posix())
    log.info("  mame:      %s", mame_path.as_posix())
    log.info("  trivia:    %s", trivia_path.as_posix())
    log.info("  sum(mame): %s", mame_sum_path.as_posix())
    log.info("  sum(hist): %s", hist_sum_path.as_posix())
    log.info("  sum(ini):  %s", ini_sum_path.as_posix())
    log.info("  sum(xfrm): %s", xform_sum_path.as_posix())

    wiki_doc = _load_json(wiki_path, "Exotica wiki data")
    wiki_games = wiki_doc.get("games") or {}
    if not isinstance(wiki_games, dict) or not wiki_games:
        raise RuntimeError("Exotica wiki data has no 'games' mapping; run the pipeline first?")

    trivia_doc = _load_json(trivia_path, "GH system trivia")
    trivia_by_machine = _normalise_trivia_root(trivia_doc)

    mame_machines = _load_json(mame_path, "MAME machines")

    # Load summaries
    mame_summary = _load_json(mame_sum_path, "MAME parsing summary")
    history_summary = _load_json(hist_sum_path, "History parsing summary")
    ini_summary = _load_json(ini_sum_path, "INI parsing summary")
    transform_summary = _load_json(xform_sum_path, "Transform summary")

    machine_order = sorted(wiki_games.keys())

    return PreviewData(
        wiki_doc=wiki_doc,
        wiki_games=wiki_games,
        trivia_by_machine=trivia_by_machine,
        mame_machines=mame_machines,
        mame_summary=mame_summary,
        history_summary=history_summary,
        ini_summary=ini_summary,
        transform_summary=transform_summary,
        machine_order=machine_order,
    )


# ----------------------------------------------------------------------------
# Generic helpers
# ----------------------------------------------------------------------------

def _pretty_json(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False)


def _sorted_pairs_from_mapping(mapping: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """
    Sort mapping by numeric value descending if possible; otherwise by key.

    Returns a list of (key, value) pairs.
    """
    pairs = list(mapping.items())
    try:
        pairs.sort(key=lambda kv: (kv[1] if isinstance(kv[1], (int, float)) else -1), reverse=True)
        return pairs
    except Exception:  # noqa: BLE001
        return sorted(pairs, key=lambda kv: str(kv[0]))


def _top_n_from_mapping(mapping: Dict[str, Any], n: int = 5) -> List[str]:
    pairs = _sorted_pairs_from_mapping(mapping)
    out: List[str] = []
    for k, v in pairs[:n]:
        out.append(f"{k}: {v}")
    return out


def _overview_headlines(labels_and_values: List[Tuple[str, Any]]) -> List[Dict[str, Any]]:
    return [{"label": label, "value": value} for label, value in labels_and_values]


def _as_dict(obj: Any) -> Dict[str, Any]:
    return obj if isinstance(obj, dict) else {}


def _as_list(obj: Any) -> List[Any]:
    return obj if isinstance(obj, list) else []


# ----------------------------------------------------------------------------
# Home-page overview builders
# ----------------------------------------------------------------------------

def _build_mame_overview(mame_summary: Dict[str, Any]) -> Dict[str, Any]:
    totals = _as_dict(mame_summary.get("totals"))
    headlines = _overview_headlines(
        [
            ("Total machines", totals.get("total_machines", "unknown")),
            ("Total parents", totals.get("total_parents", "unknown")),
            ("Total clones", totals.get("total_clones", "unknown")),
            ("is bios", totals.get("total_isbios", totals.get("total_is_bios", "unknown"))),
            ("is device", totals.get("total_isdevice", totals.get("total_is_device", "unknown"))),
            ("is mechanical", totals.get("total_ismechanical", "unknown")),
            ("requires samples", totals.get("total_requires_samples", "unknown")),
        ]
    )

    findings: List[Dict[str, Any]] = []

    for title, key in [
        ("Top display types", "display_types_distribution"),
        ("Top controls (players)", "players_per_machine_distribution"),
    ]:
        dist = totals.get(key)
        if isinstance(dist, dict) and dist:
            findings.append({"title": title, "items": _top_n_from_mapping(dist, 5)})

    inv = totals.get("invalid_displays_dropped")
    if isinstance(inv, dict) and inv.get("count"):
        examples = _as_list(inv.get("examples"))
        lines = [f"Count: {inv.get('count')}"]
        for ex in examples[:5]:
            if isinstance(ex, dict):
                lines.append(
                    f"{ex.get('machine', '?')}: {ex.get('type', '?')} "
                    f"{ex.get('width', '?')}x{ex.get('height', '?')} "
                    f"{ex.get('tag', '')}".strip()
                )
            else:
                lines.append(str(ex))
        findings.append({"title": "Invalid displays dropped (examples)", "items": lines})

    anomalies = _as_dict(mame_summary.get("anomalies"))
    if anomalies.get("count"):
        examples2 = _as_list(anomalies.get("examples"))
        lines2 = [f"Count: {anomalies.get('count')}"]
        for ex in examples2[:5]:
            lines2.append(str(ex))
        findings.append({"title": "Anomalies (examples)", "items": lines2})

    return {"headlines": headlines, "findings": findings}


def _build_history_overview(history_summary: Dict[str, Any]) -> Dict[str, Any]:
    totals = _as_dict(history_summary.get("totals"))
    sections_found = _as_dict(history_summary.get("sections_found"))
    found = _as_dict(history_summary.get("found"))

    overview_sf = _as_dict(sections_found.get("overview"))
    technical_sf = _as_dict(sections_found.get("technical"))

    headlines = _overview_headlines(
        [
            ("Systems total", totals.get("systems_total", totals.get("total_systems", "unknown"))),
            ("Software total", totals.get("software_total", totals.get("total_software", "unknown"))),
            ("Entries total", totals.get("entries_total", totals.get("total_entries", "unknown"))),
            ("Systems with PORTS", totals.get("systems_with_ports", "unknown")),
            ("Overview sections (systems)", overview_sf.get("systems_count", "unknown")),
            ("Technical sections (systems)", technical_sf.get("systems_count", "unknown")),
        ]
    )

    findings: List[Dict[str, Any]] = []

    blocks = _as_dict(found.get("blocks"))
    by_type = blocks.get("by_type")
    if isinstance(by_type, dict) and by_type:
        findings.append({"title": "Trivia blocks by type (top 5)", "items": _top_n_from_mapping(by_type, 5)})

    platforms_found = _as_dict(found.get("platforms_found"))
    by_platform = platforms_found.get("by_platform")
    if isinstance(by_platform, dict) and by_platform:
        findings.append({"title": "Platforms found (top 5)", "items": _top_n_from_mapping(by_platform, 5)})

    anomalies = _as_dict(history_summary.get("anomalies"))
    if anomalies:
        lines: List[str] = []
        for k, v in anomalies.items():
            if isinstance(v, dict) and v.get("count"):
                lines.append(f"{k}: {v.get('count')}")
            elif isinstance(v, int) and v > 0:
                lines.append(f"{k}: {v}")
        if lines:
            findings.append({"title": "Anomaly groups (non-zero)", "items": lines[:5]})

    return {"headlines": headlines, "findings": findings}


def _build_ini_overview(ini_summary: Dict[str, Any]) -> Dict[str, Any]:
    ini = _as_dict(ini_summary.get("ini"))
    files = _as_dict(ini.get("files"))

    def _sec_counts(file_key: str) -> Dict[str, int]:
        f = _as_dict(files.get(file_key))
        sc = f.get("section_counts_listed")
        return sc if isinstance(sc, dict) else {}

    game_counts = _sec_counts("game_status")
    cat_counts = _sec_counts("category")
    type_counts = _sec_counts("type")

    type_na = type_counts.get("<not available>", 0)
    type_total = sum(int(v) for v in type_counts.values() if isinstance(v, int))
    distinct_types = len([k for k in type_counts.keys() if k != "<not available>"])

    return {
        "game_or_no_game": [
            {"label": "<not available>", "value": game_counts.get("<not available>", "unknown")},
            {"label": "Game", "value": game_counts.get("Game", "unknown")},
            {"label": "No Game", "value": game_counts.get("No Game", "unknown")},
        ],
        "machine_category": [
            {"label": "Arcade", "value": cat_counts.get("Arcade", "unknown")},
            {"label": "Coin-Op (Games)", "value": cat_counts.get("Coin-Op (Games)", "unknown")},
            {"label": "Coin-Op (Non-Games)", "value": cat_counts.get("Coin-Op (Non-Games)", "unknown")},
            {"label": "Computers", "value": cat_counts.get("Computers", "unknown")},
            {"label": "Consoles", "value": cat_counts.get("Consoles", "unknown")},
            {"label": "Electronic", "value": cat_counts.get("Electronic", "unknown")},
            {"label": "Gambling", "value": cat_counts.get("Gambling", "unknown")},
            {"label": "Hardware", "value": cat_counts.get("Hardware", "unknown")},
        ],
        "machine_type": [
            {"label": "<not available>", "value": type_na},
            {"label": "Types observed", "value": distinct_types},
            {"label": "Total entries", "value": type_total},
        ],
    }


def _build_transform_overview(transform_summary: Dict[str, Any]) -> Dict[str, Any]:
    counts = _as_dict(transform_summary.get("counts"))
    selection = _as_dict(transform_summary.get("selection"))
    ports = _as_dict(transform_summary.get("ports"))

    headlines = _overview_headlines(
        [
            ("MAME total", counts.get("mame_total", "unknown")),
            ("Parents total", counts.get("parents_total", "unknown")),
            ("Clones total", counts.get("clones_total", "unknown")),
            ("Eligible parents", counts.get("eligible_parents", "unknown")),
            ("Final included", counts.get("final_included", selection.get("included_parents_total", "unknown"))),
            ("Parents with clones", counts.get("parents_with_clones", "unknown")),
        ]
    )

    findings: List[Dict[str, Any]] = []

    excluded = transform_summary.get("excluded_parents_by_reason")
    if isinstance(excluded, dict) and excluded:
        findings.append({"title": "Excluded by reason (top 5)", "items": _top_n_from_mapping(excluded, 5)})

    if ports:
        lines: List[str] = []
        gh_arcade = ports.get("gh_arcade_entries_with_ports_total")
        if gh_arcade is not None:
            lines.append(f"GH arcade entries with ports: {gh_arcade}")

        own = ports.get("included_parents_with_own_ports")
        if isinstance(own, dict):
            lines.append(f"Included parents with own ports: {own.get('count', 'unknown')}")

        clones = ports.get("included_clones_with_ports")
        if isinstance(clones, dict):
            lines.append(f"Included clones with ports: {clones.get('count', 'unknown')}")

        out_scope = ports.get("gh_arcade_entries_with_ports_excluded_by_ini")
        if isinstance(out_scope, dict):
            lines.append(f"Ports excluded by INI scope: {out_scope.get('count', 'unknown')}")

        if lines:
            findings.append({"title": "PORTS coverage", "items": lines[:5]})

    return {"headlines": headlines, "findings": findings}


# ----------------------------------------------------------------------------
# Summary page contexts
# ----------------------------------------------------------------------------

def _prep_mame_summary_page_context(mame_summary: Dict[str, Any]) -> Dict[str, Any]:
    header = _as_dict(mame_summary.get("header"))
    totals = _as_dict(mame_summary.get("totals"))

    dist_specs: List[Tuple[str, str]] = [
        ("Players per machine", "players_per_machine_distribution"),
        ("Buttons per machine", "buttons_per_machine_distribution"),
        ("Display types", "display_types_distribution"),
        ("Orientations", "orientations_distribution"),
        ("Refresh rates (rounded)", "refresh_rates_rounded_distribution"),
        ("Speakers per machine", "speakers_per_machine_distribution"),
        ("Sound channels per machine", "sound_channels_per_machine_distribution"),
        ("CPU manufacturers", "cpu_manufacturers_distribution"),
        ("CPU families", "cpu_families_distribution"),
    ]

    distributions: List[Tuple[str, List[Tuple[str, Any]]]] = []
    for title, key in dist_specs:
        dist = totals.get(key)
        if isinstance(dist, dict) and dist:
            distributions.append((title, _sorted_pairs_from_mapping(dist)))

    example_groups: List[Dict[str, Any]] = []

    invalid_displays = totals.get("invalid_displays_dropped")
    if isinstance(invalid_displays, dict) and (invalid_displays.get("count") or invalid_displays.get("examples")):
        lines: List[str] = []
        cnt = invalid_displays.get("count")
        if cnt is not None:
            lines.append(f"Count: {cnt}")
        examples = _as_list(invalid_displays.get("examples"))
        for ex in examples[:25]:
            if isinstance(ex, dict):
                machine = ex.get("machine", "?")
                dtype = ex.get("type", "?")
                w = ex.get("width", "?")
                h = ex.get("height", "?")
                tag = ex.get("tag", "")
                line = f"{machine}: {dtype} {w}x{h}"
                if tag:
                    line = f"{line} ({tag})"
                lines.append(line)
            else:
                lines.append(str(ex))
        example_groups.append({"title": "Invalid displays dropped", "items": lines})

    anomalies = mame_summary.get("anomalies")
    if isinstance(anomalies, dict) and (anomalies.get("count") or anomalies.get("examples")):
        lines2: List[str] = []
        cnt2 = anomalies.get("count")
        if cnt2 is not None:
            lines2.append(f"Count: {cnt2}")
        examples2 = _as_list(anomalies.get("examples"))
        for ex in examples2[:25]:
            lines2.append(str(ex))
        example_groups.append({"title": "Anomalies", "items": lines2})

    raw_json = _pretty_json(mame_summary)

    return {
        "header": header,
        "totals": totals,
        "distributions": distributions,
        "example_groups": example_groups,
        "raw_json": raw_json,
    }


def _prep_history_summary_page_context(history_summary: Dict[str, Any]) -> Dict[str, Any]:
    header = _as_dict(history_summary.get("header"))
    totals = _as_dict(history_summary.get("totals"))
    sections_found = _as_dict(history_summary.get("sections_found"))
    found = _as_dict(history_summary.get("found"))

    found_blocks_by_type: List[Tuple[str, Any]] = []
    blocks = _as_dict(found.get("blocks"))
    by_type = blocks.get("by_type")
    if isinstance(by_type, dict) and by_type:
        found_blocks_by_type = _sorted_pairs_from_mapping(by_type)

    found_platforms: List[Tuple[str, Any]] = []
    platforms_found = _as_dict(found.get("platforms_found"))
    by_platform = platforms_found.get("by_platform")
    if isinstance(by_platform, dict) and by_platform:
        found_platforms = _sorted_pairs_from_mapping(by_platform)

    anomalies_nonzero: List[str] = []
    anomalies = history_summary.get("anomalies")
    if isinstance(anomalies, dict):
        for group_name, obj in anomalies.items():
            if isinstance(obj, dict):
                c = obj.get("count")
                if isinstance(c, int) and c > 0:
                    anomalies_nonzero.append(f"{group_name}: {c}")
            elif isinstance(obj, int) and obj > 0:
                anomalies_nonzero.append(f"{group_name}: {obj}")
        anomalies_nonzero.sort()

    raw_json = _pretty_json(history_summary)

    return {
        "header": header,
        "totals": totals,
        "sections_found": sections_found,
        "found_blocks_by_type": found_blocks_by_type,
        "found_platforms": found_platforms,
        "anomalies_nonzero": anomalies_nonzero,
        "raw_json": raw_json,
    }


def _prep_ini_summary_page_context(ini_summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Template-friendly context for summary_ini.html.

    We avoid using ".items" from dicts in templates by providing explicit lists.
    """
    header = _as_dict(ini_summary.get("header"))
    ini = _as_dict(ini_summary.get("ini"))
    files = _as_dict(ini.get("files"))

    file_cards: List[Dict[str, Any]] = []
    for key in ["game_status", "category", "type"]:
        f = _as_dict(files.get(key))
        section_counts = f.get("section_counts_listed")
        pairs = _sorted_pairs_from_mapping(section_counts) if isinstance(section_counts, dict) else []
        file_cards.append(
            {
                "key": key,
                "filename": f.get("filename"),
                "version": f.get("version"),
                "entries_listed": f.get("entries_listed"),
                "sections_total": f.get("sections_total"),
                "section_counts_pairs": pairs,
                "raw": f,
            }
        )

    totals = _as_dict(ini_summary.get("totals"))
    raw_json = _pretty_json(ini_summary)

    return {
        "header": header,
        "totals": totals,
        "file_cards": file_cards,
        "raw_json": raw_json,
    }


def _prep_transform_summary_page_context(transform_summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Template-friendly context for summary_transform.html.

    Provides both raw dicts and pre-sorted lists so templates can iterate safely.
    """
    header = _as_dict(transform_summary.get("header"))
    counts = _as_dict(transform_summary.get("counts"))
    selection = _as_dict(transform_summary.get("selection"))
    ports = _as_dict(transform_summary.get("ports"))

    excluded = transform_summary.get("excluded_parents_by_reason")
    excluded_pairs = _sorted_pairs_from_mapping(excluded) if isinstance(excluded, dict) else []

    raw_json = _pretty_json(transform_summary)

    return {
        "header": header,
        "counts": counts,
        "selection": selection,
        "ports": ports,
        "excluded_pairs": excluded_pairs,
        "raw_json": raw_json,
    }


# ----------------------------------------------------------------------------
# Flask application factory
# ----------------------------------------------------------------------------

def create_app(preview_data: PreviewData) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).with_name("templates")),
        static_folder=None,
    )

    app.config["MHT_PREVIEW_DATA"] = preview_data

    def _prev_next(machine: str) -> Tuple[str, str]:
        order = preview_data.machine_order
        if machine not in order:
            return machine, machine
        idx = order.index(machine)
        prev_m = order[idx - 1] if idx > 0 else order[-1]
        next_m = order[idx + 1] if idx < len(order) - 1 else order[0]
        return prev_m, next_m

    # ------------------------------------------------------------------ routes

    @app.route("/")
    def home() -> str:
        pd = preview_data
        version = active_version()

        t_hdr = _as_dict(pd.transform_summary.get("header")) if isinstance(pd.transform_summary, dict) else {}
        run = {
            "started_utc": t_hdr.get("started_utc") or pd.transform_summary.get("started_utc"),
            "finished_utc": t_hdr.get("finished_utc") or pd.transform_summary.get("finished_utc"),
            "duration_seconds": t_hdr.get("duration_seconds") or pd.transform_summary.get("duration_seconds"),
            "generated_at": t_hdr.get("generated_at"),
        }

        m_hdr = _as_dict(pd.mame_summary.get("header"))
        h_hdr = _as_dict(pd.history_summary.get("header"))
        i_hdr = _as_dict(pd.ini_summary.get("header"))

        m_ver = _as_dict(m_hdr.get("versions"))
        h_ver = _as_dict(h_hdr.get("versions"))
        i_ver = _as_dict(i_hdr.get("versions"))

        sources: Dict[str, Any] = {
            "mame": {
                "build": m_ver.get("mame_build"),
                "xml_version": m_ver.get("mame_xml_version"),
                "mameconfig": m_ver.get("mameconfig"),
                "filename": None,
            },
            "history": {
                "version": h_ver.get("gh_version"),
                "date": h_ver.get("gh_date"),
                "filename": None,
            },
            "ini": {
                "generated_at": i_ver.get("ini_generated_at"),
                "mame_xml_version": i_ver.get("mame_xml_version"),
                "filename": None,
            },
            "transform": {
                "mame_build": _as_dict(_as_dict(pd.transform_summary.get("header")).get("versions")).get("mame_build")
                if isinstance(pd.transform_summary, dict)
                else None,
                "history_version": _as_dict(_as_dict(pd.transform_summary.get("header")).get("versions")).get("history_version")
                if isinstance(pd.transform_summary, dict)
                else None,
                "history_date": _as_dict(_as_dict(pd.transform_summary.get("header")).get("versions")).get("history_date")
                if isinstance(pd.transform_summary, dict)
                else None,
                "ini_generated_at": _as_dict(_as_dict(pd.transform_summary.get("header")).get("versions")).get("ini_generated_at")
                if isinstance(pd.transform_summary, dict)
                else None,
                "filename": None,
            },
        }

        mame_overview = _build_mame_overview(pd.mame_summary)
        history_overview = _build_history_overview(pd.history_summary)
        ini_overview = _build_ini_overview(pd.ini_summary)
        transform_overview = _build_transform_overview(pd.transform_summary)

        total_games = len(pd.wiki_games)

        return render_template(
            "home.html",
            version=version,
            total_games=total_games,
            summary=pd.transform_summary,
            run=run,
            sources=sources,
            mame_overview=mame_overview,
            history_overview=history_overview,
            ini_overview=ini_overview,
            transform_overview=transform_overview,
        )

    @app.route("/summary/mame")
    def summary_mame() -> str:
        ctx = _prep_mame_summary_page_context(preview_data.mame_summary)
        return render_template("summary_mame.html", **ctx)

    @app.route("/summary/history")
    def summary_history() -> str:
        ctx = _prep_history_summary_page_context(preview_data.history_summary)
        return render_template("summary_history.html", **ctx)

    @app.route("/summary/ini")
    def summary_ini() -> str:
        ctx = _prep_ini_summary_page_context(preview_data.ini_summary)
        return render_template("summary_ini.html", **ctx)

    @app.route("/summary/transform")
    def summary_transform() -> str:
        ctx = _prep_transform_summary_page_context(preview_data.transform_summary)
        return render_template("summary_transform.html", **ctx)

    @app.route("/game/<machine>")
    def game(machine: str) -> str:
        pd = preview_data
        games = pd.wiki_games

        if machine not in games:
            abort(404)

        rec = games[machine]
        wiki_page_name = rec.get("wiki_page_name") or machine

        prev_m, next_m = _prev_next(machine)

        mame_info = pd.mame_machines.get(machine) or {}
        raw_description = mame_info.get("description") or ""

        year = rec.get("year")
        manufacturer = rec.get("manufacturer")

        opening_parts: List[str] = [f"{wiki_page_name} is an arcade video game"]
        if year and manufacturer:
            opening_parts.append(f"published in {year} by {manufacturer}.")
        elif year:
            opening_parts.append(f"published in {year}.")
        elif manufacturer:
            opening_parts.append(f"published by {manufacturer}.")
        else:
            opening_parts.append(".")
        opening_sentence = " ".join(opening_parts)

        trivia = pd.trivia_by_machine.get(machine) or {}

        # Overview blocks (no heading on page, just follows opening sentence)
        overview_blocks: List[Dict[str, Any]] = []
        overview_obj = None
        if isinstance(trivia.get("sections"), dict):
            overview_obj = trivia.get("sections", {}).get("overview")
        if isinstance(overview_obj, dict):
            blocks = overview_obj.get("blocks")
            if isinstance(blocks, list):
                overview_blocks = [b for b in blocks if isinstance(b, dict)]

        # Remaining sections
        trivia_sections: List[Dict[str, Any]] = []
        sections = trivia.get("sections")
        if isinstance(sections, dict):
            for sec_name, sec in sections.items():
                if sec_name == "overview":
                    continue
                if not isinstance(sec, dict):
                    continue
                blocks = sec.get("blocks")
                if not isinstance(blocks, list):
                    continue
                trivia_sections.append({"name": sec_name, "blocks": blocks})

        ports_display = rec.get("ports_display") or []
        mame_titles_display = rec.get("mame_titles_display")

        return render_template(
            "game.html",
            machine=machine,
            prev_machine=prev_m,
            next_machine=next_m,
            wiki_page_name=wiki_page_name,
            opening_sentence=opening_sentence,
            overview_blocks=overview_blocks,
            description=raw_description,
            record=rec,
            mame_titles_display=mame_titles_display,
            trivia_sections=trivia_sections,
            ports_display=ports_display,
        )

    @app.route("/search")
    def search() -> str:
        q = (request.args.get("q") or "").strip()
        pd = preview_data
        results: List[Dict[str, Any]] = []

        if q:
            q_ci = q.casefold()
            for machine, rec in pd.wiki_games.items():
                if q_ci in machine.casefold():
                    minfo = pd.mame_machines.get(machine) or {}
                    desc = minfo.get("description") or ""
                    year = rec.get("year")
                    manufacturer = rec.get("manufacturer")
                    results.append(
                        {
                            "machine": machine,
                            "description": desc,
                            "year": year,
                            "manufacturer": manufacturer,
                        }
                    )

        results.sort(key=lambda r: r["machine"])

        return render_template(
            "search.html",
            query=q,
            results=results,
        )

    @app.errorhandler(404)
    def not_found(e):  # type: ignore[override]
        return render_template("404.html"), 404

    return app


# ----------------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------------

def run_preview(port: int | None = None, auto_open: Optional[bool] = None) -> None:
    """
    Start the web preview server for the active release.

    - Verifies that required JSON artefacts exist.
    - Loads them into memory once.
    - Starts a Flask app on the configured port.
    - Optionally opens a browser pointing at '/'.
    """
    port = port or WEB_PREVIEW_PORT
    if auto_open is None:
        auto_open = WEB_PREVIEW_AUTO_OPEN

    try:
        preview_data = _load_preview_data()
    except Exception as exc:  # noqa: BLE001
        log.error("Cannot start web preview: %s", exc)
        return

    app = create_app(preview_data)

    url = f"http://127.0.0.1:{port}/"
    log.info("Starting MHT web preview on %s", url)

    if auto_open:

        def _open_browser() -> None:
            webbrowser.open(url)

        threading.Timer(0.8, _open_browser).start()

    # Use reloader=False so we do not double-load data.
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_preview()
