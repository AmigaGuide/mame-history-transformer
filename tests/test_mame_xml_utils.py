import xml.etree.ElementTree as ET
from mht.utils.mame_xml import element_text, attr_yesno_bool
from mht.inputs.mame_parser import _int_or_none, _yesno_str
from mht.utils.summaries import bucket_key_int

def test_element_text_defaults_and_strip():
    root = ET.fromstring("<m><year>  1985 </year></m>")
    assert element_text(root, "year") == "1985"
    assert element_text(root, "missing", default="") == ""

def test_attr_yesno_bool_variants():
    el = ET.fromstring('<m isbios="Yes" isdevice="no" meh="maybe"/>')
    assert attr_yesno_bool(el, "isbios") is True
    assert attr_yesno_bool(el, "isdevice") is False
    assert attr_yesno_bool(el, "meh") is False
    assert attr_yesno_bool(el, "absent") is False

def test_int_helpers_and_buckets():
    assert _int_or_none("3") == 3
    assert _int_or_none("") is None
    assert bucket_key_int(0) == "0"
    assert bucket_key_int(None) == "unknown"

def test_yesno_str():
    assert _yesno_str(True) == "yes"
    assert _yesno_str(False) == "no"
