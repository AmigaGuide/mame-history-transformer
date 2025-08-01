"""
platform_usage_report.py

Generates a list of all unique platform names found in gh_entries,
along with the <system> names each platform appears under.

This tool is intended for ad hoc inspection only and is not part of the main pipeline.
Copy into your project and run manually when needed to audit platform naming consistency.

Author: Jason (XtC) Skelly (Open University TM470, 2025)
"""

from collections import defaultdict
from pathlib import Path
import json

# Load preprocessed Gaming-History entries
with open("output/gh_entries.json", "r", encoding="utf-8") as f:
    gh_entries = json.load(f)

# Group platforms with their associated system names
platform_to_systems = defaultdict(list)

for system_name, data in gh_entries.items():
    for section, ports in data.get("ports", {}).items():
        for port in ports:
            platform = port.get("platform")
            if platform:
                platform_to_systems[platform].append(system_name)

# Count platforms and prepare output text
platform_count = len(platform_to_systems)
lines = [f"Unique Platforms Found: {platform_count}", ""]

for platform in sorted(platform_to_systems):
    systems = platform_to_systems[platform]
    lines.append(f"{platform}  —  {len(systems)} use(s)")
    for sys in sorted(systems):
        lines.append(f"  - {sys}")
    lines.append("")  # Blank line between platforms

# Write results to file with count in filename
output_path = Path(f"findings/2025-08-01 - Platform Usage with System Names ({platform_count}).txt")
output_path.write_text("\n".join(lines), encoding="utf-8")

print(f"Platform usage summary written to: {output_path}")
