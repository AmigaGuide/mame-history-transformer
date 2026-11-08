"""Source-backed provenance fields for the preview landing page.

Do not infer filenames or timestamps from configured paths or timestamps from
other stages.  Source summaries are the authority for this view.
"""
from __future__ import annotations

from typing import Any

from .formatting import as_dict, header_versions
from .preview_data import PreviewData


def _meaningful(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def _inputs(summary: dict) -> list[dict]:
    records = as_dict(summary.get("provenance")).get("inputs")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _source_file(record: dict, *, placeholder: str) -> str | None:
    """Use a verified ZIP member or a non-placeholder recorded source name."""
    member = _meaningful(record.get("zip_member"))
    if member:
        return member
    name = _meaningful(record.get("name"))
    if name and name.casefold() != placeholder.casefold():
        return name
    return None


def _ini_files(summary: dict) -> list[dict]:
    labels = (
        ("game_status", "Game Or No Game.ini"),
        ("category", "Machine Category.ini"),
        ("type", "Machine Type.ini"),
    )
    inputs = _inputs(summary)
    files = as_dict(as_dict(summary.get("ini")).get("files"))
    result = []
    for index, (key, label) in enumerate(labels):
        record = inputs[index] if index < len(inputs) else {}
        summary_file = as_dict(files.get(key))
        # The summary builder uses key as its fallback filename. Never present
        # that internal identifier as a real input filename.
        recorded = _source_file(record, placeholder=key)
        if not recorded:
            candidate = _meaningful(summary_file.get("filename"))
            if candidate and candidate.casefold() != key.casefold():
                recorded = candidate
        result.append({
            "label": label,
            "filename": recorded,
            "archive": _meaningful(record.get("zip_archive")),
            "modified": _meaningful(record.get("zip_member_modified")),
        })
    return result


def build_source_provenance(data: PreviewData) -> dict:
    """Create presentation data without changing or completing the summaries."""
    m_versions = header_versions(data.mame_summary)
    h_versions = header_versions(data.history_summary)
    i_versions = header_versions(data.ini_summary)
    t_versions = header_versions(data.transform_summary)
    m = next(iter(_inputs(data.mame_summary)), {})
    h = next(iter(_inputs(data.history_summary)), {})
    return {
        "mame": {
            "build": m_versions.get("mame_build"),
            "xml_version": m_versions.get("mame_xml_version"),
            "mameconfig": m_versions.get("mameconfig"),
            "filename": _source_file(m, placeholder="mame.xml"),
            "archive": _meaningful(m.get("zip_archive")),
            "modified": _meaningful(m.get("zip_member_modified")),
        },
        "history": {
            "version": h_versions.get("gh_version"),
            "date": h_versions.get("gh_date"),
            "filename": _source_file(h, placeholder="history.xml"),
            "archive": _meaningful(h.get("zip_archive")),
            "modified": _meaningful(h.get("zip_member_modified")),
        },
        "ini": {
            "generated_at": i_versions.get("ini_generated_at"),
            "mame_xml_version": i_versions.get("mame_xml_version"),
            "files": _ini_files(data.ini_summary),
        },
        "transform": {
            "mame_build": t_versions.get("mame_build"),
            "history_version": t_versions.get("history_version"),
            "history_date": t_versions.get("history_date"),
            "ini_generated_at": t_versions.get("ini_generated_at"),
        },
    }
