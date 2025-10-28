import subprocess, sys, re

def test_root_shows_help_and_not_running_pipeline(tmp_path, monkeypatch):
    # Run the module with no args: expect help text, not pipeline output keywords.
    proc = subprocess.run([sys.executable, "-m", "mht", "-h"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "usage: mht" in proc.stdout
    # And with no flags:
    proc2 = subprocess.run([sys.executable, "-m", "mht"], capture_output=True, text=True)
    assert proc2.returncode == 0
    assert "usage: mht" in proc2.stdout
    assert "Starting full MAME XML parsing" not in proc2.stdout
