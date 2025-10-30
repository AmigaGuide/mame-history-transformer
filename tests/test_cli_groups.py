import subprocess, sys


def test_incoming_group_help():
    proc = subprocess.run([sys.executable, "-m", "mht", "incoming"], capture_output=True, text=True)
    assert proc.returncode != 2  # should not be argparse error
    assert "usage: mht incoming" in proc.stdout
    assert "scan" in proc.stdout and "adopt" in proc.stdout and "verify" in proc.stdout
