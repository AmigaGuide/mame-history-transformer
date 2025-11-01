from __future__ import annotations

import re

# Headings like '----- PORTS -----' (case-insensitive).
SECTION_PATTERN = re.compile(r"^-+\s+([A-Z0-9 &]+)\s+-+$", re.IGNORECASE)

# Category headings inside PORTS, e.g. '* CONSOLES:'
CATEGORY_HEADING_PATTERN = re.compile(r"^\*\s*([A-Z0-9 &]+)\s*:\s*$", re.IGNORECASE)

# Expected top-level PORTS categories (unchanged behaviour)
KNOWN_PLATFORMS: set[str] = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}

# --- Section headings canonicalisation ---------------------------------------

# Canonical headings as they appear in GH (OPENING is implicit → overview)
STANDARD_SECTION_HEADERS = {
    "TECHNICAL", "TRIVIA", "UPDATES", "SCORING", "TIPS AND TRICKS",
    "SERIES", "STAFF", "PORTS", "CONTRIBUTE", "CAST OF CHARACTERS"
}

# Hand-maintained alias map (exact string after normalisation → canonical)
# Add to this when you find recurring variants.
SECTION_ALIASES = {
    "TIPS & TRICKS": "TIPS AND TRICKS",
    "TIP AND TRICKS": "TIPS AND TRICKS",
    "UPDATE": "UPDATES",
    "CAST OF CHARACTER": "CAST OF CHARACTERS",  # keep as non-standard; example
    # etc.
}

def _norm_spaces(s: str) -> str:
    return " ".join(s.split())

def normalise_section_heading(raw: str) -> str:
    """
    Normalise a GH section heading for comparison.
    - Strip leading/trailing whitespace
    - Collapse internal whitespace
    - Uppercase
    """
    return _norm_spaces((raw or "").strip()).upper()
