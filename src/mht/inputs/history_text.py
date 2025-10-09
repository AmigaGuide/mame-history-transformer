from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, List

__all__ = ["SECTION_PATTERN", "segment_text_sections"]

# ----- dashed headings like "----- PORTS -----" (case-insensitive)
SECTION_PATTERN = re.compile(r"^-+\s+([A-Z0-9 &]+)\s+-+$", re.IGNORECASE)

def segment_text_sections(text: str, parsing_state: Dict) -> Dict[str, List[str]]:
    """
    Split a GH <text> block into named sections; preserve blank lines only in PORTS.
    Mutates parsing_state['section_headings_found'] (Counter).
    """
    sections = defaultdict(list)
    current_section = "OVERVIEW"

    for raw in text.splitlines():
        norm = re.sub(r"\u00A0", " ", raw or "")
        line = norm.strip()

        # dashed section heading
        m = SECTION_PATTERN.match(line)
        if m:
            name = m.group(1).strip().upper()
            parsing_state.setdefault("section_headings_found", Counter())[name] += 1
            current_section = name
            continue

        if line == "":
            if current_section == "PORTS":
                sections[current_section].append("")  # keep separator for block detection
            continue

        sections[current_section].append(line)

    return sections
