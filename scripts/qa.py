from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_MARKERS = ("pyproject.toml", "requirements.txt", "README.md")

SECTIONS = [
    ("MAME summary", "data/mame_parsing_summary.json", {
        "total_machines": "n/a",
        "parents": "n/a",
        "clones": "n/a",
        "requires_samples": "n/a",
        # This may be absent on older runs; we handle that.
        "dropped_displays": "n/a",
    }),
    ("GH summary", "data/history_parsing_summary.json", {
        # These keys vary between versions; we print n/a if missing.
        "systems_total": "n/a",
        "ports_total": "n/a",
        "anomalies_total": "n/a",
    }),
    ("INI summary", "data/ini_parsing_summary.json", {
        "machines_classified": "n/a",
        "unknowns": "n/a",
    }),
    ("Transform summary", "data/transform_summary.json", {
        "parents_included": "n/a",
        "parents_dropped": "n/a",
        "wiki_pages": "n/a",
        "ports_duplicate_systems": "n/a",
    }),
]

def project_root(start: Path) -> Path:
    """Find the repo root by walking up until we see expected markers."""
    p = start.resolve()
    for _ in range(10):
        if any((p / m).exists() for m in PROJECT_MARKERS) and (p / "tests").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return start.resolve()

def run_pytest(cwd: Path) -> tuple[int, str, str]:
    """Run pytest -q and return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    return proc.returncode, proc.stdout, proc.stderr

def load_json(path: Path) -> Dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None

def val(d: Dict[str, Any], key: str, default: Any) -> Any:
    """Fetch a top-level key; if absent, try some common alternates, else default."""
    if d is None:
        return "n/a"
    if key in d:
        return d.get(key, default)

    # Common alternates / older names:
    alternates = {
        "parents": ("total_parents", "parents_total"),
        "clones": ("total_clones", "clones_total"),
        "requires_samples": ("total_requires_samples", "requires_samples_total"),
        "dropped_displays": ("dropped_displays_total",),
        "systems_total": ("systems_parsed", "systems_count", "systems"),
        "ports_total": ("ports_parsed", "ports_count"),
        "anomalies_total": ("anomalies",),
        "machines_classified": ("classified_total", "machines_count"),
        "unknowns": ("unknown_total", "unknown_count"),
        "parents_included": ("final_included", "included_parents"),
        "parents_dropped": ("dropped_parents",),
        "wiki_pages": ("pages_total",),
        "ports_duplicate_systems": ("port_dupe_systems",),
    }.get(key, ())

    for alt in alternates:
        if alt in d:
            return d.get(alt, default)
    return default

def main() -> int:
    here = Path(__file__).parent
    root = project_root(here)

    print("==> Running tests")
    code, out, err = run_pytest(root)
    # Show a terse result line, then (if helpful) the first pytest line when nothing ran.
    if code == 0:
        print("Tests passed")
    else:
        print("Tests failed")
        if "no tests ran" in out.lower():
            print("\n(no tests ran — check working directory and test file names)")
    # Optional: uncomment to see details when needed
    # print(out.strip())
    # if err.strip():
    #     print("\n[stderr]")
    #     print(err.strip())

    # Summaries
    for title, relpath, keys in SECTIONS:
        print(f"\n-- {title} ({relpath})")
        data = load_json(root / relpath)
        for k, default in keys.items():
            print(f"{k.replace('_', ' '):<18}: {val(data, k, default)}")

    print("\nDone.")
    return code

if __name__ == "__main__":
    raise SystemExit(main())
