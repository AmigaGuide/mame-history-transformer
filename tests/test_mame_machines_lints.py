import json
import pathlib
import warnings

#DOC = pathlib.Path("output/mame_machines.json")


# show warnings in pytest output
warnings.filterwarnings("default")

def test_display_lints_warn_only(outputs_dir):
    DOC = (outputs_dir / "mame_machines.json")
    d = json.loads(DOC.read_text(encoding="utf-8"))

    bad = []
    soft = []

    allowed_types = {"raster", "vector", "lcd", "svg"}

    for mach, rec in d.items():
        for i, disp in enumerate(rec.get("displays", [])):
            dtype = disp.get("type")
            w = disp.get("width")
            h = disp.get("height")

            # Hard anomaly candidates (but we only WARN here; schema test will fail anyway)
            if isinstance(w, int) and isinstance(h, int):
                if (w == 0 and (h or 0) > 0) or ((w or 0) > 0 and h == 0):
                    bad.append((mach, i, f"zero dimension: width={w}, height={h}"))

            # Soft anomaly: type missing/unknown (you want visibility)
            if dtype is None or (isinstance(dtype, str) and dtype.lower() not in allowed_types):
                soft.append((mach, i, f"type={dtype!r}"))

    if bad:
        warnings.warn(f"{len(bad)} display(s) with zero dimension (first 10): {bad[:10]}")
    if soft:
        warnings.warn(f"{len(soft)} display(s) with missing/unknown type (first 10): {soft[:10]}")

    # This test does NOT fail — it only warns to surface potential data issues.
    assert True
