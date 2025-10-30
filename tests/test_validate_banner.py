import subprocess, sys


def test_validate_shows_release(monkeypatch):
    proc = subprocess.run([sys.executable, "-m", "mht", "validate"], capture_output=True, text=True)
    # Either OK or failed is fine; key is that it echoes the release.
    assert "[validate] release =" in (proc.stdout + proc.stderr)
