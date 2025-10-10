# Canonical schema IDs
SCHEMA_IDS = {
    "mame":      "mht.mame.summary",
    "history":   "mht.history.summary",
    "ini":       "mht.ini.summary",
    "transform": "mht.transform.summary",
}

# Schema versions (JSON contract versions)
SCHEMA_INFO = {
    SCHEMA_IDS["mame"]:      "1.0.1",
    SCHEMA_IDS["history"]:   "1.0.1",
    SCHEMA_IDS["ini"]:       "1.0.1",
    SCHEMA_IDS["transform"]: "1.0.1",
}

# Tool/module versions (your code)
TOOL_VERSIONS = {
    "mame_parser":    "1.0.24",
    "history_parser": "1.0.8",
    "ini_summary":    "1.0.5",
    "transformer":    "1.0.25",
}

# ===== Output dataset schemas (centralise the IDs + versions your transformer emits) =====
OUTPUT_SCHEMAS = {
    "wiki":   {"id": "exotica_lit_wiki",                "version": "1.1.0"},
    "raw":    {"id": "exotica_lit_raw_data",            "version": "1.1.0"},
    "pages":  {"id": "exotica_wiki_pages_and_redirects","version": "1.1.0"},
}


def schema_version(schema_id: str) -> str:
    return SCHEMA_INFO[schema_id]

def tool_version(tool_name: str) -> str:
    return TOOL_VERSIONS[tool_name]

def output_schema(name: str) -> dict:
    # returns {"id": ..., "version": ...}
    return OUTPUT_SCHEMAS[name]
