from __future__ import annotations

"""
Flask application factory for the MHT web preview.

Routes are kept here so server startup remains a thin wrapper and so the route
module can focus on request/response and template contexts only.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from flask import Flask, Response, abort, render_template, request

from mht.utils.paths import active_version

from .formatting import as_dict, format_duration_seconds, format_utc_iso, header_versions
from .overview import (
    build_history_overview,
    build_ini_overview,
    build_mame_overview,
    build_transform_overview,
)
from .preview_data import JsonDict, PreviewData
from .provenance import build_source_provenance
from .catalogue import select_catalogue_page
from .summary_contexts import (
    prep_history_summary_page_context,
    prep_ini_summary_page_context,
    prep_mame_summary_page_context,
    prep_transform_summary_page_context,
)


def create_app(
    preview_data: PreviewData,
    version: str | None = None,
) -> Flask:
    """
    Create and configure the Flask application for the web preview.

    The caller is responsible for loading PreviewData first so we can load once
    and run with the Flask reloader disabled.
    """
    version = active_version(version)
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

        t_hdr = as_dict(pd.transform_summary.get("header"))

        run = {
            "started_utc": format_utc_iso(t_hdr.get("started_utc") or pd.transform_summary.get("started_utc")),
            "finished_utc": format_utc_iso(t_hdr.get("finished_utc") or pd.transform_summary.get("finished_utc")),
            "duration_seconds": format_duration_seconds(
                t_hdr.get("duration_seconds") or pd.transform_summary.get("duration_seconds")
            ),
            "generated_at": format_utc_iso(t_hdr.get("generated_at")),
        }

        sources = build_source_provenance(pd)

        return render_template(
            "home.html",
            version=version,
            total_games=len(pd.wiki_games),
            total_preview_games=len(pd.machine_order),
            first_machine=pd.machine_order[0] if pd.machine_order else None,
            first_game_name=(
                (pd.wiki_games.get(pd.machine_order[0]) or {}).get("wiki_page_name")
                or (pd.mame_machines.get(pd.machine_order[0]) or {}).get("description")
                or pd.machine_order[0]
            ) if pd.machine_order else None,
            summary=pd.transform_summary,
            run=run,
            sources=sources,
            mame_overview=build_mame_overview(pd.mame_summary),
            history_overview=build_history_overview(pd.history_summary),
            ini_overview=build_ini_overview(pd.ini_summary),
            transform_overview=build_transform_overview(pd.transform_summary),
        )

    @app.route("/summary/<stage>/source.json")
    def download_summary_json(stage: str) -> Response:
        """Download an in-memory summary; never read an arbitrary file path."""
        summaries = {
            "mame": preview_data.mame_summary,
            "history": preview_data.history_summary,
            "ini": preview_data.ini_summary,
            "transform": preview_data.transform_summary,
        }
        if stage not in summaries:
            abort(404)

        payload = json.dumps(summaries[stage], indent=2, ensure_ascii=False) + "\n"
        return Response(
            payload,
            content_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="mht_{stage}_summary.json"'},
        )

    @app.route("/summary/mame")
    def summary_mame() -> str:
        ctx = prep_mame_summary_page_context(preview_data.mame_summary)
        return render_template("summary_mame.html", **ctx)

    @app.route("/summary/history")
    def summary_history() -> str:
        ctx = prep_history_summary_page_context(preview_data.history_summary)
        return render_template("summary_history.html", version=version, **ctx)

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
        if machine not in pd.machine_order:
            abort(404)

        published_rec = pd.wiki_games.get(machine)
        is_published = published_rec is not None
        mame_info = pd.mame_machines.get(machine) or {}
        # Canonical MAME fields are useful when no wiki record exists.
        rec = published_rec if published_rec is not None else mame_info
        raw_description = mame_info.get("description") or ""
        wiki_page_name = rec.get("wiki_page_name") or raw_description or machine

        prev_m, next_m = _prev_next(machine)

        opening_sentence = rec.get("opening_sentence")

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
                trivia_sections.append({
                    "name": sec_name,
                    "title": sec_name.replace("_", " ").capitalize(),
                    "anchor": f"trivia-section-{len(trivia_sections) + 1}",
                    "blocks": blocks,
                })

        return render_template(
            "game.html",
            machine=machine,
            is_published=is_published,
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

    @app.route("/diagnostics")
    def diagnostics() -> str:
        from .diagnostics import build_diagnostic_groups
        return render_template(
            "diagnostics.html",
            diagnostic_groups=build_diagnostic_groups(preview_data),
        )

    @app.route("/catalogue")
    def catalogue() -> str:
        selection = select_catalogue_page(
            preview_data,
            query=request.args.get("q", ""),
            status=request.args.get("status", "all"),
            trivia=request.args.get("trivia", "any"),
            page=request.args.get("page", "1"),
        )
        return render_template("catalogue.html", **selection)

    @app.route("/search")
    def search() -> str:
        q = (request.args.get("q") or "").strip()
        pd = preview_data
        results: List[JsonDict] = []

        if q:
            q_ci = q.casefold()
            for machine in pd.machine_order:
                if q_ci in machine.casefold():
                    published_rec = pd.wiki_games.get(machine) or {}
                    minfo = pd.mame_machines.get(machine) or {}
                    results.append(
                        {
                            "machine": machine,
                            "description": (minfo.get("description") or ""),
                            "year": published_rec.get("year") or minfo.get("year"),
                            "manufacturer": published_rec.get("manufacturer") or minfo.get("manufacturer"),
                        }
                    )

        results.sort(key=lambda r: r["machine"])

        return render_template("search.html", query=q, results=results)

    @app.errorhandler(404)
    def not_found(_e):  # type: ignore[override]
        return render_template("404.html"), 404

    return app
