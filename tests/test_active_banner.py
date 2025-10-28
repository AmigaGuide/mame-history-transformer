import subprocess, sys

def _run(args):
    proc = subprocess.run([sys.executable, "-m", "mht", *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr

def test_root_shows_active_banner_and_help():
    # Root invocation should show the active banner and the top-level help
    code, out = _run([])
    assert "[active] release =" in out
    assert "usage: mht" in out
    assert "status" in out and "run" in out  # a couple of subcommands visible

def test_status_subcommand_shows_active_banner():
    # Subcommands also show the banner (not asserting exit code)
    code, out = _run(["status", "-v", "0999"])
    assert "[active] release =" in out
    assert "(root: data/releases/0999)" in out
