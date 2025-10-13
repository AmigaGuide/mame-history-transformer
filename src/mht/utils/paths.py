from __future__ import annotations
from pathlib import Path

# Base folders (relative to repo root)
DATA_DIR   = Path("data")
OUTPUT_DIR = Path("output")
STAMPS_DIR = DATA_DIR / ".stamps"

# Source artefacts
MAME_XML     = DATA_DIR / "mame.xml"
HISTORY_XML  = DATA_DIR / "history.xml"
INI_GAME     = DATA_DIR / "[GAMING HISTORY] Game Or No Game.ini"
INI_CATEGORY = DATA_DIR / "[GAMING HISTORY] Machine Category.ini"
INI_TYPE     = DATA_DIR / "[GAMING HISTORY] Machine Type.ini"

# Data Helpers
TITLE_OVERRIDES = DATA_DIR / "title_overrides.json"
RUN_MANIFEST    = DATA_DIR / "run_manifest.json"

# Contracts / schema directory
CONTRACTS_DIR = Path("src") / "mht" / "contracts"

# Specific schema files used by the CLI validator
EXOTICA_RAW_SCHEMA   = CONTRACTS_DIR / "exotica_lit_raw_data.schema.json"
EXOTICA_WIKI_SCHEMA  = CONTRACTS_DIR / "exotica_lit_wiki.schema.json"
EXOTICA_PAGES_SCHEMA = CONTRACTS_DIR / "exotica_wiki_pages_and_redirects.schema.json"

# (Optional extras if/when you want them:)
# GH_SYSTEM_PORTS_SCHEMA   = CONTRACTS_DIR / "gh_system_ports.schema.json"
# GH_INI_CLASS_SCHEMA      = CONTRACTS_DIR / "gh_ini_classifications.schema.json"
# MAME_MACHINES_SCHEMA     = CONTRACTS_DIR / "mame_machines.schema.json"
# MAME_PARENT_INDEX_SCHEMA = CONTRACTS_DIR / "mame_parent_index.schema.json"

# Cache of detected encodings + version strings
ENCODINGS_JSON = DATA_DIR / "encodings.json"

# Stage summaries
MAME_SUMMARY     = DATA_DIR / "mame_parsing_summary.json"
HISTORY_SUMMARY  = DATA_DIR / "history_parsing_summary.json"
INI_SUMMARY      = DATA_DIR / "ini_parsing_summary.json"
TRANSFORM_SUMMARY= DATA_DIR / "transform_summary.json"

# Intermediate/outputs
MAME_MACHINES_PATH   = OUTPUT_DIR / "mame_machines.json"
PARENT_INDEX_PATH    = OUTPUT_DIR / "mame_parent_index.json"
GH_SYSTEM_PORTS_PATH = OUTPUT_DIR / "gh_system_ports.json"
INI_CLASS_PATH       = OUTPUT_DIR / "gh_ini_classifications.json"

# Final deliverables
EXOTICA_RAW   = OUTPUT_DIR / "exotica_lit_raw_data.json"
EXOTICA_WIKI  = OUTPUT_DIR / "exotica_lit_wiki.json"
EXOTICA_PAGES = OUTPUT_DIR / "exotica_wiki_pages_and_redirects.json"

def ensure_dirs() -> None:
    """Create common output dirs if missing (safe to call often)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STAMPS_DIR.mkdir(parents=True, exist_ok=True)
