import json

import pytest

from mht.utils import transform_io


@pytest.fixture
def input_paths(tmp_path, monkeypatch):
    paths = {
        "mame": tmp_path / "mame_machines.json",
        "parents": tmp_path / "mame_parent_index.json",
        "ports": tmp_path / "gh_system_ports.json",
        "ini": tmp_path / "gh_ini_classifications.json",
    }

    monkeypatch.setattr(
        transform_io,
        "mame_machines_path",
        lambda: paths["mame"],
    )
    monkeypatch.setattr(
        transform_io,
        "parent_index_path",
        lambda: paths["parents"],
    )
    monkeypatch.setattr(
        transform_io,
        "gh_system_ports_path",
        lambda: paths["ports"],
    )
    monkeypatch.setattr(
        transform_io,
        "ini_classifications_path",
        lambda: paths["ini"],
    )

    for path in paths.values():
        path.write_text("{}", encoding="utf-8")

    return paths


def test_valid_transform_inputs_are_loaded(input_paths):
    input_paths["mame"].write_text(
        json.dumps({"pacman": {"description": "Pac-Man"}}),
        encoding="utf-8",
    )

    mame, parents, ports, ini = transform_io.load_stage_inputs()

    assert "pacman" in mame
    assert parents == {}
    assert ports == {}
    assert ini == {}


def test_missing_required_input_is_rejected(input_paths):
    input_paths["ports"].unlink()

    with pytest.raises(ValueError, match="could not be loaded"):
        transform_io.load_stage_inputs()


def test_invalid_json_is_rejected(input_paths):
    input_paths["ini"].write_text(
        "{ this is not valid JSON",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="could not be loaded"):
        transform_io.load_stage_inputs()


def test_wrong_json_structure_is_rejected(input_paths):
    input_paths["parents"].write_text(
        "[]",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not a JSON object"):
        transform_io.load_stage_inputs()


def test_empty_json_objects_remain_valid(input_paths):
    result = transform_io.load_stage_inputs()

    assert result == ({}, {}, {}, {})
