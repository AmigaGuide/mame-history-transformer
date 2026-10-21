import argparse
import runpy

from mht.cli import cmd_run


def test_cli_run_preserves_success_exit_code(monkeypatch):
    def fake_run_path(*args, **kwargs):
        raise SystemExit(0)

    monkeypatch.setattr(runpy, "run_path", fake_run_path)

    assert cmd_run(argparse.Namespace()) == 0


def test_cli_run_preserves_failure_exit_code(monkeypatch):
    def fake_run_path(*args, **kwargs):
        raise SystemExit(1)

    monkeypatch.setattr(runpy, "run_path", fake_run_path)

    assert cmd_run(argparse.Namespace()) == 1


def test_cli_run_preserves_other_failure_codes(monkeypatch):
    def fake_run_path(*args, **kwargs):
        raise SystemExit(2)

    monkeypatch.setattr(runpy, "run_path", fake_run_path)

    assert cmd_run(argparse.Namespace()) == 2


def test_cli_run_handles_non_numeric_exit(monkeypatch):
    def fake_run_path(*args, **kwargs):
        raise SystemExit("Pipeline failed")

    monkeypatch.setattr(runpy, "run_path", fake_run_path)

    assert cmd_run(argparse.Namespace()) == 1
