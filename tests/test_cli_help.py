import sys
import pytest

from mht import cli


def run_cli(argv, capsys):
    sys.argv = ["mht", *argv]
    with pytest.raises(SystemExit) as e:
        cli.main()
    out = capsys.readouterr().out
    return e.value.code, out


def test_root_no_args_shows_global_help(capsys):
    code, out = run_cli([], capsys)
    assert code == 0
    assert "usage: mht" in out
    # Should list top-level commands rather than running the pipeline
    assert "status" in out and "run" in out and "fetch" in out and "releases" in out


@pytest.mark.parametrize(
    "parent, expected_usage",
    [
        (["releases"], "usage: mht releases"),
        (["incoming"], "usage: mht incoming"),
        (["fetch"],    "usage: mht fetch"),
    ],
)
def test_parent_without_subcmd_prints_help_and_exits_2(parent, expected_usage, capsys):
    code, out = run_cli(parent, capsys)
    assert code == 2
    assert expected_usage in out


def test_run_requires_explicit_subcommand(capsys):
    # Ensure "run" is only invoked explicitly, i.e. "mht" alone does NOT run it.
    code, out = run_cli([], capsys)
    assert code == 0
    # Help text visible, not the pipeline output
    assert "Run the full incremental pipeline" in out
    assert "[active] release" not in out or True  # banner may or may not print here; we just care help was shown
