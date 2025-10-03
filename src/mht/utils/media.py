from __future__ import annotations
import re
from collections import Counter
from typing import Iterable, Sequence

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
