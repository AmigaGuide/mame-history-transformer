from __future__ import annotations

import re

# Headings like '----- PORTS -----' (case-insensitive).
SECTION_PATTERN = re.compile(r"^-+\s+([A-Z0-9 &]+)\s+-+$", re.IGNORECASE)

# Category headings inside PORTS, e.g. '* CONSOLES:'
CATEGORY_HEADING_PATTERN = re.compile(r"^\*\s*([A-Z0-9 &]+)\s*:\s*$", re.IGNORECASE)

# Expected top-level PORTS categories (unchanged behaviour)
KNOWN_PLATFORMS: set[str] = {"CONSOLES", "COMPUTERS", "HANDHELDS", "OTHERS"}
