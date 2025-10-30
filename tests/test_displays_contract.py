import json


def _groups(doc):
    for rec in (doc.get("games") or {}).values():
        disp = rec.get("displays") or {}
        for g in (disp.get("groups") or []):
            yield g

def test_vector_svg_have_no_dims(outputs_dir):
    RAW_PATH = (outputs_dir / "exotica_lit_raw_data.json")
    doc = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    for g in _groups(doc):
        t = g.get("type")
        if t in {"Vector", "SVG"}:
            assert g.get("width") is None and g.get("height") is None

def test_raster_lcd_have_dims(outputs_dir):
    RAW_PATH = (outputs_dir / "exotica_lit_raw_data.json")
    doc = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    for g in _groups(doc):
        t = g.get("type")
        if t in {"Raster", "LCD"}:
            assert isinstance(g.get("width"), int) and g["width"] > 0
            assert isinstance(g.get("height"), int) and g["height"] > 0
