from __future__ import annotations

"""
Flask application factory for the MHT web preview.

Routes are kept here so server startup remains a thin wrapper and so the route
module can focus on request/response and template contexts only.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple

from flask import Flask, abort, render_template, request

from mht.utils.paths import active_version

from .formatting import as_dict, header_versions
from .overview import (
    build_history_overview,
    build_ini_overview,
    build_mame_overview,
    build_transform_overview,
)
from .preview_data import JsonDict, PreviewData
from .summary_contexts import (
    prep_history_summary_page_context,
    prep_ini_summary_page_context,
    prep_mame_summary_page_context,
    prep_transform_summary_page_context,
)


def create_app(preview_data: PreviewData) -> Flask:
    """
    Create and configure the Flask application for the web preview.

    The caller is responsible for loading PreviewData first so we can load once
    and run with the Flask reloader disabled.
    """
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).with_name("templates")),
        static_folder=None,
    )

    app.config["MHT_PREVIEW_DATA"] = preview_data

    def _prev_next(machine: str) -> Tuple[str, str]:
        """Return (prev_machine, next_machine) according to the stable machine_order."""
        order = preview_data.machine_order
        if machine not in order:
            return machine, machine

        idx = order.index(machine)
        prev_m = order[idx - 1] if idx > 0 else order[-1]
        next_m = order[idx + 1] if idx < len(order) - 1 else order[0]
        return prev_m, next_m

    @app.route("/")
    def home() -> str:
        pd = preview_data
        version = active_version()

        t_hdr = as_dict(pd.transform_summary.get("header"))
        run = {
            "started_utc": t_hdr.get("started_utc") or pd.transform_summary.get("started_utc"),
            "finished_utc": t_hdr.get("finished_utc") or pd.transform_summary.get("finished_utc"),
            "duration_seconds": t_hdr.get("duration_seconds") or pd.transform_summary.get("duration_seconds"),
            "generated_at": t_hdr.get("generated_at"),
        }

        m_ver = header_versions(pd.mame_summary)
        h_ver = header_versions(pd.history_summary)
        i_ver = header_versions(pd.ini_summary)
        t_ver = header_versions(pd.transform_summary)

        sources: JsonDict = {
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
                "mame_build": t_ver.get("mame_build"),
                "history_version": t_ver.get("history_version"),
                "history_date": t_ver.get("history_date"),
                "ini_generated_at": t_ver.get("ini_generated_at"),
                "filename": None,
            },
        }

        return render_template(
            "home.html",
            version=version,
            total_games=len(pd.wiki_games),
            summary=pd.transform_summary,
            run=run,
            sources=sources,
            mame_overview=build_mame_overview(pd.mame_summary),
            history_overview=build_history_overview(pd.history_summary),
            ini_overview=build_ini_overview(pd.ini_summary),
            transform_overview=build_transform_overview(pd.transform_summary),
        )

    @app.route("/summary/mame")
    def summary_mame() -> str:
        ctx = prep_mame_summary_page_context(preview_data.mame_summary)
        return render_template("summary_mame.html", **ctx)

    @app.route("/summary/history")
    def summary_history() -> str:
        ctx = prep_history_summary_page_context(preview_data.history_summary)
        return render_template("summary_history.html", **ctx)

    @app.route("/summary/ini")
    def summary_ini() -> str:
        ctx = prep_ini_summary_page_context(preview_data.ini_summary)
        return render_template("summary_ini.html", **ctx)

    @app.route("/summary/transform")
    def summary_transform() -> str:
        ctx = prep_transform_summary_page_context(preview_data.transform_summary)
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

        overview_blocks: List[JsonDict] = []
        overview_obj = None
        if isinstance(trivia.get("sections"), dict):
            overview_obj = trivia.get("sections", {}).get("overview")
        if isinstance(overview_obj, dict):
            blocks = overview_obj.get("blocks")
            if isinstance(blocks, list):
                overview_blocks = [b for b in blocks if isinstance(b, dict)]

        trivia_sections: List[JsonDict] = []
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
            mame_titles_display=rec.get("mame_titles_display"),
            trivia_sections=trivia_sections,
            ports_display=rec.get("ports_display") or [],
        )

    @app.route("/search")
    def search() -> str:
        q = (request.args.get("q") or "").strip()
        pd = preview_data
        results: List[JsonDict] = []

        if q:
            q_ci = q.casefold()
            for machine, rec in pd.wiki_games.items():
                if q_ci in machine.casefold():
                    minfo = pd.mame_machines.get(machine) or {}
                    results.append(
                        {
                            "machine": machine,
                            "description": (minfo.get("description") or ""),
                            "year": rec.get("year"),
                            "manufacturer": rec.get("manufacturer"),
                        }
                    )

        results.sort(key=lambda r: r["machine"])

        return render_template("search.html", query=q, results=results)

    @app.errorhandler(404)
    def not_found(_e):  # type: ignore[override]
        return render_template("404.html"), 404

    return app
