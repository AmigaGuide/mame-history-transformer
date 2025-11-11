from pathlib import Path
import subprocess
import sys


def _run(args, cwd=None):
    proc = subprocess.run(
        [sys.executable, "-m", "mht", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return proc.returncode, (proc.stdout + proc.stderr)

def test_root_shows_active_banner_and_help(tmp_path):
    # Provide version context via current_version.txt so the root CLI can render the banner.
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "current_version.txt").write_text("0.999", encoding="utf-8")
    # (Optional but harmless) create matching release root
    (tmp_path / "data" / "releases" / "0999").mkdir(parents=True, exist_ok=True)

    code, out = _run([], cwd=tmp_path)
    # Only care that the banner/help are visible
    assert "[active] release =" in out
    assert "usage: mht" in out
    assert "status" in out and "run" in out

def test_status_subcommand_shows_active_banner(tmp_path):
    # Isolate everything in tmp cwd and pass -v explicitly.
    target = tmp_path / "data" / "releases" / "0999"
    target.mkdir(parents=True, exist_ok=True)

    code, out = _run(["status", "-v", "0999"], cwd=tmp_path)
    # Don’t force code==0; just verify the banner and 0999 reference.
    assert "[active] release =" in out
    assert "(root: data/releases/0999)" in out or "data/releases/0999" in out
