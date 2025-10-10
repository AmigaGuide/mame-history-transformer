from __future__ import annotations
import re
from collections import Counter
from typing import Iterable, Sequence, Dict, List, Tuple, Optional
from xml.etree.ElementTree import Element

_MEDIA_ORDER = {
    "GD-ROM": 100,
    "DVD-ROM": 90,
    "CD-ROM": 80,
    "LaserDisc": 70,
    "Capacitance Electronic Disc (CED)": 60,
    "Hard disk": 50,
    "CompactFlash card": 40,
    "Secure Digital card": 30,
    "NAND flash": 20,
    "USB storage": 10,
    "VHS tape": 0,
}

def normalise_device_to_media(raw: str) -> str | None:
    s = (raw or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]+", s))
    if (
        "laserdisc" in tokens
        or any(t.startswith("laserdisc") for t in tokens)
        or re.search(r"\b(ld_)?(ldv1000|pr7820|pr8210a?|22vp932)\b", s)
    ):
        return "LaserDisc"
    if "ced_videodisc" in tokens:
        return "Capacitance Electronic Disc (CED)"
    if "gdrom" in tokens:
        return "GD-ROM"
    if {"dvdrom", "dvd"} & tokens or any(t.startswith("dvdrom") for t in tokens):
        return "DVD-ROM"
    if (
        {"cdrom", "cd", "audiocd", "cdxa", "xm3301", "cr589", "stvcd"} & tokens
        or any(t.startswith("cdrom") for t in tokens)
    ):
        return "CD-ROM"
    if {"hdd", "harddisk", "scsi_hdd_image"} & tokens or ":hdd" in s:
        return "Hard disk"
    if {"cf", "cfcard", "cflash", "ataflash", "taitocf", "taitopccard1", "taitopccard2", "pccard"} & tokens:
        return "CompactFlash card"
    if {"sdcard", "internalsd"} & tokens:
        return "Secure Digital card"
    if "nand" in tokens:
        return "NAND flash"
    if "usb" in tokens:
        return "USB storage"
    if "vhs" in tokens:
        return "VHS tape"
    return None

def normalise_device_list_to_media(devs: Iterable[str] | str | None) -> list[str]:
    if devs is None:
        return []
    seq = devs if isinstance(devs, (list, tuple)) else [devs]
    out, seen = [], set()
    for raw in seq:
        label = normalise_device_to_media(str(raw))
        if not label:
            continue
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            out.append(label)
    return out

def order_media_labels(labels: list[str]) -> list[str]:
    # stable + precedence ordering
    labels = list(dict.fromkeys(labels))
    return sorted(labels, key=lambda s: (-_MEDIA_ORDER.get(s, -1), s.casefold()))

def bytes_to_binary_human(n: int) -> tuple[float, str] | None:
    if n is None:
        return None
    KB = 1024
    MB = 1024 ** 2
    GB = 1024 ** 3
    if n >= GB:
        return (n / GB, "GiB")
    if n >= MB:
        return (n / MB, "MiB")
    if n >= KB:
        return (n / KB, "KiB")
    return None

def join_with_ampersand(items: Sequence[str]) -> str:
    n = len(items)
    if n == 0: return ""
    if n == 1: return items[0]
    if n == 2: return f"{items[0]} & {items[1]}"
    return f"{', '.join(items[:-1])} & {items[-1]}"

def disk_required_and_regions(machine_elem: Element) -> Tuple[str, List[str], Dict[str, int]]:
    """
    Return (disk_required, disk_regions_unique_sorted, regions_overall_counts) from <disk> elements.

    - disk_required: "yes" if any <disk> exists, else "no".
    - disk_regions_unique_sorted: unique region keys (lowercased; "" -> "unknown") sorted ascending.
    - regions_overall_counts: counts per region across all <disk> elements (not deduped).
    """
    disk_elems = machine_elem.findall("disk")
    disk_required = "yes" if disk_elems else "no"

    regions_set = set()
    regions_overall: Dict[str, int] = {}
    for d in disk_elems:
        region_raw = (d.attrib.get("region") or "").strip()
        region_key = region_raw.lower() if region_raw else "unknown"
        regions_set.add(region_key)
        regions_overall[region_key] = regions_overall.get(region_key, 0) + 1

    disk_regions = sorted(regions_set)
    return disk_required, disk_regions, regions_overall

def summarise_device_refs(machine_elem: Element) -> Dict[str, object]:
    """
    Summarise <device_ref name="..."> entries for 'samples' and 'speaker'.

    Returns a dict shaped exactly like the existing parser output:
        {"samples": "yes" | "no", "speaker": <int_count>}
    """
    has_samples = False
    speaker_ref_count = 0
    for dref in machine_elem.findall("device_ref"):
        name = (dref.attrib.get("name") or "").strip().lower()
        if name == "samples":
            has_samples = True
        elif name == "speaker":
            speaker_ref_count += 1
    return {"samples": "yes" if has_samples else "no", "speaker": speaker_ref_count}

def extract_sound_channels(machine_elem: Element) -> Optional[int]:
    """
    Read <sound channels="..."> from a <machine> element and return an int or None.

    - If <sound> is absent, returns None.
    - If the 'channels' attribute is present and purely digits, returns int(channels).
    - Otherwise returns None.

    This mirrors the previous inline logic from mame_parser.
    """
    sound_el = machine_elem.find("sound")
    if sound_el is None:
        return None
    raw = (sound_el.attrib.get("channels") or "").strip()
    return int(raw) if raw.isdigit() else None
