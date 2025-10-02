from __future__ import annotations
import sys
import runpy
from pathlib import Path

def main() -> None:
    # If no subcommand, behave like before (call main.py)
    if len(sys.argv) == 1:
        repo_root = Path(__file__).resolve().parents[2]
        entry = repo_root / "main.py"
        if entry.exists():
            src_dir = repo_root / "src"
            if src_dir.exists():
                sys.path.insert(0, str(src_dir))
            runpy.run_path(str(entry), run_name="__main__")
            return
    # Otherwise, use our CLI
    from mht.cli import main as cli_main
    cli_main()

if __name__ == "__main__":
    main()
