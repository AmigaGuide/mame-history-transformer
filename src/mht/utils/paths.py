from __future__ import annotations
from pathlib import Path
from typing import Optional

# Repo roots
REPO_ROOT = Path(".")
DATA_DIR  = REPO_ROOT / "data"

# Back-compat (until encodings move into per-release manifest)
ENCODINGS_JSON = DATA_DIR / "encodings.json"

# Shared, version-agnostic locations
LOOKUPS_DIR = DATA_DIR / "lookups"
TITLE_OVERRIDES = LOOKUPS_DIR / "title_overrides.json"

CONTRACTS_DIR = REPO_ROOT / "src" / "mht" / "contracts"

# Specific schema files used by the CLI validator (unchanged)
EXOTICA_RAW_SCHEMA   = CONTRACTS_DIR / "exotica_lit_raw_data.schema.json"
EXOTICA_WIKI_SCHEMA  = CONTRACTS_DIR / "exotica_lit_wiki.schema.json"
EXOTICA_PAGES_SCHEMA = CONTRACTS_DIR / "exotica_wiki_pages_and_redirects.schema.json"
# Optional extras (kept as comments)
# GH_SYSTEM_PORTS_SCHEMA   = CONTRACTS_DIR / "gh_system_ports.schema.json"
# GH_INI_CLASS_SCHEMA      = CONTRACTS_DIR / "gh_ini_classifications.schema.json"
# MAME_MACHINES_SCHEMA     = CONTRACTS_DIR / "mame_machines.schema.json"
# MAME_PARENT_INDEX_SCHEMA = CONTRACTS_DIR / "mame_parent_index.schema.json"

# ---------------------------------------------------------------------
# Active version resolution
# ---------------------------------------------------------------------

_CURRENT_VERSION_TXT = DATA_DIR / "current_version.txt"

def _read_current_version_file() -> Optional[str]:
    try:
        s = _CURRENT_VERSION_TXT.read_text(encoding="utf-8").strip()
        return s if s else None
    except FileNotFoundError:
        return None

def _infer_single_release() -> Optional[str]:
    rel_root = DATA_DIR / "releases"
    if not rel_root.exists():
        return None
    try:
        candidates = [p.name for p in rel_root.iterdir() if p.is_dir()]
    except FileNotFoundError:
        return None
    # If there is exactly one release folder, use it as a convenience.
    return candidates[0] if len(candidates) == 1 else None

def active_version(version_override: Optional[str] = None) -> str:
    """
    Decide which release version to operate on.
    Order: explicit override -> current_version.txt -> only release present.
    """
    if version_override and version_override.strip():
        return version_override.strip()
    v = _read_current_version_file()
    if v:
        return v
    v = _infer_single_release()
    if v:
        return v
    raise ValueError(
        "No active version set. Create data/current_version.txt with a version (e.g. '0280') "
        "or pass --version in the CLI, or create data/releases/<ver>/ first."
    )

# ---------------------------------------------------------------------
# Per-release directories & files
# ---------------------------------------------------------------------

def release_root(version: Optional[str] = None) -> Path:
    v = active_version(version)
    return DATA_DIR / "releases" / v

def archives_dir(version: Optional[str] = None) -> Path:
    return release_root(version) / "archives"

def extracted_dir(version: Optional[str] = None) -> Path:
    return release_root(version) / "extracted"

def summaries_dir(version: Optional[str] = None) -> Path:
    return release_root(version) / "summaries"

def outputs_dir(version: Optional[str] = None) -> Path:
    return release_root(version) / "outputs"

def stamps_dir(version: Optional[str] = None) -> Path:
    return release_root(version) / ".stamps"

def manifest_path(version: Optional[str] = None) -> Path:
    return release_root(version) / "manifest.json"

def run_manifest_path(version: Optional[str] = None) -> Path:
    return summaries_dir(version) / "run_manifest.json"

# ---------------------------------------------------------------------
# Canonical source artefacts (extracted-first phase)
# ---------------------------------------------------------------------

def mame_xml_path(version: Optional[str] = None) -> Path:
    return extracted_dir(version) / "mame.xml"

def history_xml_path(version: Optional[str] = None) -> Path:
    return extracted_dir(version) / "history.xml"

def ini_game_path(version: Optional[str] = None) -> Path:
    return extracted_dir(version) / "[GAMING HISTORY] Game Or No Game.ini"

def ini_category_path(version: Optional[str] = None) -> Path:
    return extracted_dir(version) / "[GAMING HISTORY] Machine Category.ini"

def ini_type_path(version: Optional[str] = None) -> Path:
    return extracted_dir(version) / "[GAMING HISTORY] Machine Type.ini"

# ---------------------------------------------------------------------
# Stage summaries (read/write)
# ---------------------------------------------------------------------

def mame_summary_path(version: Optional[str] = None) -> Path:
    return summaries_dir(version) / "mame_parsing_summary.json"

def history_summary_path(version: Optional[str] = None) -> Path:
    return summaries_dir(version) / "history_parsing_summary.json"

def ini_summary_path(version: Optional[str] = None) -> Path:
    return summaries_dir(version) / "ini_parsing_summary.json"

def transform_summary_path(version: Optional[str] = None) -> Path:
    return summaries_dir(version) / "transform_summary.json"

# ---------------------------------------------------------------------
# Intermediate/inputs to transform (pre-transform JSONs)
# ---------------------------------------------------------------------

def mame_machines_path(version: Optional[str] = None) -> Path:
    return outputs_dir(version) / "mame_machines.json"

def parent_index_path(version: Optional[str] = None) -> Path:
    return outputs_dir(version) / "mame_parent_index.json"

def gh_system_ports_path(version: Optional[str] = None) -> Path:
    return outputs_dir(version) / "gh_system_ports.json"

def ini_classifications_path(version: Optional[str] = None) -> Path:
    return outputs_dir(version) / "gh_ini_classifications.json"

# ---------------------------------------------------------------------
# Final deliverables
# ---------------------------------------------------------------------

def exotica_raw_path(version: Optional[str] = None) -> Path:
    return outputs_dir(version) / "exotica_lit_raw_data.json"

def exotica_wiki_path(version: Optional[str] = None) -> Path:
    return outputs_dir(version) / "exotica_lit_wiki.json"

def exotica_pages_path(version: Optional[str] = None) -> Path:
    return outputs_dir(version) / "exotica_wiki_pages_and_redirects.json"

# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------

def title_overrides_path() -> Path:
    return TITLE_OVERRIDES

def ensure_release_dirs(version: Optional[str] = None) -> None:
    """
    Create the standard folder set for the active (or given) release.
    Safe to call repeatedly.
    """
    for d in (archives_dir(version), extracted_dir(version),
              summaries_dir(version), outputs_dir(version), stamps_dir(version)):
        d.mkdir(parents=True, exist_ok=True)



# ---------------------------------------------------------------------
# Back-compat aliases (deprecated)
# These keep older modules running while we migrate everything to helpers.
# They resolve using the *current* active version at import time.
# ---------------------------------------------------------------------
OUTPUT_DIR = outputs_dir()
STAMPS_DIR = stamps_dir()

# legacy per-file constants
MAME_XML = mame_xml_path()
HISTORY_XML = history_xml_path()
INI_GAME = ini_game_path()
INI_CATEGORY = ini_category_path()
INI_TYPE = ini_type_path()

MAME_MACHINES_PATH = mame_machines_path()
PARENT_INDEX_PATH = parent_index_path()
GH_SYSTEM_PORTS_PATH = gh_system_ports_path()
INI_CLASS_PATH = ini_classifications_path()

MAME_SUMMARY = mame_summary_path()
HISTORY_SUMMARY = history_summary_path()
INI_SUMMARY = ini_summary_path()
TRANSFORM_SUMMARY = transform_summary_path()

EXOTICA_RAW = exotica_raw_path()
EXOTICA_WIKI = exotica_wiki_path()
EXOTICA_PAGES = exotica_pages_path()

RUN_MANIFEST = run_manifest_path()
