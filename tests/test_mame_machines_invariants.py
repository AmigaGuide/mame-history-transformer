import json
import pathlib

DOC = pathlib.Path("output/mame_machines.json")

def test_counts_and_arrays_line_up():
    d = json.loads(DOC.read_text(encoding="utf-8"))

    for mach, rec in d.items():
        # displays count matches list length
        assert rec["display_count"] == len(rec.get("displays", [])), f"{mach}: display_count mismatch"

        # chips: cpu_count and sound_chip_count match filtered chips by type
        chips = rec.get("chips", [])
        cpu_ct = sum(1 for c in chips if c.get("type") == "cpu")
        aud_ct = sum(1 for c in chips if c.get("type") == "audio")
        assert cpu_ct == rec["cpu_count"], f"{mach}: cpu_count mismatch"
        assert aud_ct == rec["sound_chip_count"], f"{mach}: sound_chip_count mismatch"

        # device_ref usually 1 item; if present, speaker >= 0 and samples yes/no
        for dr in rec.get("device_ref", []):
            assert dr["samples"] in {"yes","no"}
            assert isinstance(dr["speaker"], int) and dr["speaker"] >= 0

def test_controls_buttons_non_negative_when_present():
    d = json.loads(DOC.read_text(encoding="utf-8"))
    for mach, rec in d.items():
        for ctrl in rec.get("controls", []):
            btns = ctrl.get("buttons")
            if btns is not None:
                assert isinstance(btns, int) and btns >= 0, f"{mach}: negative/non-int buttons"
