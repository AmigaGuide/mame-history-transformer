import subprocess, sys, pytest


def run_cli(args):
    proc = subprocess.run([sys.executable, "-m", "mht", *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr

@pytest.mark.parametrize(
    "parent, expected_usage",
    [
        (["releases"], "usage: mht releases"),
        (["fetch"],    "usage: mht fetch"),
    ],
)
def test_parent_without_subcmd_prints_help_and_exits_2(parent, expected_usage):
    code, out = run_cli(parent)
    # Argparse-style error for groups that require a subcmd
    assert code == 2
    assert expected_usage in out

def test_incoming_without_subcmd_prints_help_and_exits_0():
    code, out = run_cli(["incoming"])
    # Friendly group help for 'incoming'
    assert code == 0
    assert "usage: mht incoming" in out
    assert "scan" in out and "adopt" in out and "verify" in out
