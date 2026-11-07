"""Canonical stamp contracts for MHT's four processing stages.

This module defines *what* constitutes an up-to-date stage. It does not
run parsers, select archives or decide whether a stage may execute.

The supplied ``source`` must be the same primary source chosen by the runner.
When omitted, History/INI are marked as missing-source by the CLI; MAME
uses its extracted-file fallback. The transformer requires a SNAPS archive.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mht.utils import paths
from mht.transform.snaps_genres import GENRE_DESCRIPTIONS_PATH


@dataclass(frozen=True)
class StageContract:
    name: str
    tool: str
    inputs: tuple[Path, ...]
    outputs: tuple[Path, ...]
    missing_source: bool = False
    optional_inputs: tuple[Path, ...] = ()

    @property
    def schema_id(self) -> str:
        return f"mht.stage.{self.name}"

    @property
    def stamp_filename(self) -> str:
        return f"{self.name}.json"


def stage_contract(
    name: str,
    version: str,
    *,
    source: Path | None = None,
    snaps_archive: Path | None = None,
) -> StageContract:
    """Return stamp metadata and I/O for the requested release and stage.

    ``source`` is the history ZIP for INI/History or the MAME ZIP/XML for MAME.
    ``snaps_archive`` is required for a valid transform stage.
    """
    enc_cache = paths.encodings_cache_path(version)

    if name == "ini":
        return StageContract(
            name, "ini_summary",
            (source, enc_cache) if source is not None else (enc_cache,),
            (paths.ini_classifications_path(version), paths.ini_summary_path(version)),
            missing_source=source is None,
        )
    if name == "mame":
        return StageContract(
            name, "mame_parser",
            (source or paths.mame_xml_path(version), enc_cache),
            (
                paths.mame_machines_path(version),
                paths.parent_index_path(version),
                paths.mame_summary_path(version),
            ),
        )
    if name == "history":
        return StageContract(
            name, "history_parser",
            (source, enc_cache) if source is not None else (enc_cache,),
            (
                paths.gh_system_ports_path(version),
                paths.gh_system_trivia_path(version),
                paths.history_summary_path(version),
            ),
            missing_source=source is None,
        )
    if name == "transform":
        overrides = paths.title_overrides_path()
        inputs = (
            paths.mame_machines_path(version),
            paths.ini_classifications_path(version),
            paths.parent_index_path(version),
            paths.gh_system_ports_path(version),
            paths.mame_summary_path(version),
            paths.history_summary_path(version),
            paths.ini_summary_path(version),
            overrides,
            GENRE_DESCRIPTIONS_PATH,
        )
        if snaps_archive is not None:
            inputs += (snaps_archive,)
        return StageContract(
            name, "transformer", inputs,
            (
                paths.exotica_wiki_path(version),
                paths.exotica_raw_path(version),
                paths.exotica_pages_path(version),
                paths.transform_summary_path(version),
            ),
            missing_source=snaps_archive is None,
            optional_inputs=(overrides,),
        )
    raise ValueError(f"Unknown stage: {name!r}")
