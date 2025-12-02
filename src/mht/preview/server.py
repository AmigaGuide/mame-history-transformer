from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from flask import Flask, abort, render_template, request

from mht.utils.config import WEB_PREVIEW_PORT, WEB_PREVIEW_AUTO_OPEN
from mht.utils.logger import setup_logger
from mht.utils.paths import (
    exotica_wiki_path,
    mame_machines_path,
    transform_summary_path,
    gh_system_trivia_path,
)
from mht.utils.paths import active_version, outputs_dir  # assuming you have these

log = setup_logger(__name__)


# ----------------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------------

@dataclass
class PreviewData:
    wiki_doc: Dict[str, Any]
    wiki_games: Dict[str, Dict[str, Any]]
    trivia_by_machine: Dict[str, Any]
    mame_machines: Dict[str, Dict[str, Any]]
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
    summary_path = transform_summary_path()
    trivia_path = _find_trivia_path()

    log.info("Web preview loading artefacts from active release %s", active_version())
    log.info("  wiki:   %s", wiki_path.as_posix())
    log.info("  mame:   %s", mame_path.as_posix())
    log.info("  trivia: %s", trivia_path.as_posix())
    log.info("  summary:%s", summary_path.as_posix())

    wiki_doc = _load_json(wiki_path, "Exotica wiki data")
    wiki_games = wiki_doc.get("games") or {}
    if not isinstance(wiki_games, dict) or not wiki_games:
        raise RuntimeError("Exotica wiki data has no 'games' mapping; run the pipeline first?")

    trivia_doc = _load_json(trivia_path, "GH system trivia")
    trivia_by_machine = _normalise_trivia_root(trivia_doc)

    mame_machines = _load_json(mame_path, "MAME machines")

    transform_summary = _load_json(summary_path, "Transform summary")

    machine_order = sorted(wiki_games.keys())

    return PreviewData(
        wiki_doc=wiki_doc,
        wiki_games=wiki_games,
        trivia_by_machine=trivia_by_machine,
        mame_machines=mame_machines,
        transform_summary=transform_summary,
        machine_order=machine_order,
    )


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

    # Small helper for prev/next navigation
    def _prev_next(machine: str) -> Tuple[str, str]:
        order = preview_data.machine_order
        if machine not in order:
            return machine, machine
        idx = order.index(machine)
        prev_m = order[idx - 1] if idx > 0 else order[-1]
        next_m = order[idx + 1] if idx < len(order) - 1 else order[0]
        return prev_m, next_m

    @app.context_processor
    def inject_nav_helpers() -> Dict[str, Any]:
        return {"preview_machine_order": preview_data.machine_order}

    # ------------------------------------------------------------------ routes

    @app.route("/")
    def home() -> str:
        pd = preview_data
        version = active_version()
        summary = pd.transform_summary or {}
        total_games = len(pd.wiki_games)

        return render_template(
            "home.html",
            version=version,
            summary=summary,
            total_games=total_games,
        )

    @app.route("/game/<machine>")
    def game(machine: str) -> str:
        pd = preview_data
        games = pd.wiki_games

        if machine not in games:
            abort(404)

        rec = games[machine]
        wiki_page_name = rec.get("wiki_page_name") or machine

        # Prev / next navigation
        prev_m, next_m = _prev_next(machine)

        # Description from MAME (raw) – currently only used on the search page.
        mame_info = pd.mame_machines.get(machine) or {}
        raw_description = mame_info.get("description") or ""

        year = rec.get("year")
        manufacturer = rec.get("manufacturer")

        # Opening sentence
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

        # ------------------------------------------------------------------ trivia / overview

        trivia_root = pd.trivia_by_machine.get(machine) or {}
        sections_map: Dict[str, Any] = {}

        if isinstance(trivia_root, dict):
            # Preferred shape: { "gh_id": ..., "sections_raw": {...}, "sections": {...} }
            if isinstance(trivia_root.get("sections"), dict):
                sections_map = trivia_root["sections"]
            else:
                # Fallback: older shape where section names map directly to lists/blocks.
                sections_map = {
                    k: v for k, v in trivia_root.items()
                    if isinstance(v, (list, dict))
                }

        overview_blocks: List[Dict[str, Any]] = []
        overview_section_key: Optional[str] = None

        # Extract the full ordered list of blocks from the "overview" section, if present.
        for sec_name, sec_value in sections_map.items():
            if sec_name.lower() != "overview":
                continue

            overview_section_key = sec_name

            # Newer shape: section is a dict with "blocks".
            if isinstance(sec_value, dict) and isinstance(sec_value.get("blocks"), list):
                overview_blocks = list(sec_value["blocks"])
            # Fallback: section is already a list of blocks.
            elif isinstance(sec_value, list):
                overview_blocks = list(sec_value)

            break  # only consider the first matching "overview" section

        # Build trivia_sections for the template, excluding the overview section entirely.
        trivia_sections: List[Dict[str, Any]] = []

        for sec_name, sec_value in sections_map.items():
            if overview_section_key and sec_name == overview_section_key:
                continue

            if isinstance(sec_value, dict) and isinstance(sec_value.get("blocks"), list):
                blocks = list(sec_value["blocks"])
            elif isinstance(sec_value, list):
                blocks = list(sec_value)
            else:
                continue  # unsupported shape; skip

            if not blocks:
                continue

            trivia_sections.append(
                {
                    "name": sec_name,
                    "blocks": blocks,
                }
            )

        # ------------------------------------------------------------------ ports and titles

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
