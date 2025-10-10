"""
ROM aggregation helpers.

Includes:
- rom_count_and_bytes(): counts <rom> children and sums numeric size attributes
  (non-numeric sizes ignored), returning (count, total_bytes).
"""

from __future__ import annotations
from collections import Counter
from typing import Sequence, Tuple
from xml.etree.ElementTree import Element

from mht.utils.media import (
    normalise_device_to_media,
    order_media_labels,
    bytes_to_binary_human,  # shared helper
)
from mht.utils.strings import join_with_ampersand


def format_rom_block(
    rom_count: int,
    rom_bytes_total: int,
    disk_required: str | None,
    disk_regions: Sequence[str] | str | None,
) -> str:
    """
    Produce the three-line ROM/media block:

      1) "<N> ROM(s)"
      2) "<bytes> bytes (x.xx GiB/MiB/KiB)" when applicable
      3) optional "Plus: ..." summarising normalised media devices

    Behaviour mirrors the original transformer.py logic, now centralised.
    """
    # Line 1
    line1 = f"{rom_count:,} ROM" + ("" if rom_count == 1 else "s")

    # Line 2
    total_bytes = int(rom_bytes_total or 0)
    human = bytes_to_binary_human(total_bytes)
    line2 = f"{total_bytes:,} bytes" + (f" ({human[0]:.2f} {human[1]})" if human else "")

    # Line 3 (optional “Plus: …” when disks are required)
    line3 = None
    if (disk_required or "").strip().lower() == "yes":
        seq = (
            disk_regions
            if isinstance(disk_regions, (list, tuple))
            else ([disk_regions] if disk_regions else [])
        )

        # Normalise each raw device hint to a display label
        all_labels: list[str] = []
        for raw in seq:
            lab = normalise_device_to_media(str(raw))
            if lab:
                all_labels.append(lab)

        if all_labels:
            # Count multiplicities case-insensitively
            counts = Counter(l.casefold() for l in all_labels)

            # Preserve first-seen uniqueness, then apply media ordering
            first_seen_unique = list(dict.fromkeys(all_labels))
            ordered_unique = order_media_labels(first_seen_unique)

            display_labels = []
            for lab in ordered_unique:
                n = counts[lab.casefold()]
                display_labels.append(f"({n}x) {lab}" if n > 1 else lab)

            line3 = f"Plus: {join_with_ampersand(display_labels)}"

    return "\n".join([line1, line2] + ([line3] if line3 else []))

def rom_count_and_bytes(machine_elem: Element) -> Tuple[int, int]:
    """
    Return (rom_count, rom_bytes_total) by scanning <rom> elements.

    - Counts all <rom> children.
    - Sums 'size' attributes that are purely digits; ignores non-numeric.
    - When no ROMs are present, returns (0, 0).
    """
    rom_elems = machine_elem.findall("rom")
    rom_count = len(rom_elems)
    rom_bytes_total = 0
    for r in rom_elems:
        sz = (r.attrib.get("size") or "").strip()
        if sz.isdigit():
            rom_bytes_total += int(sz)
    return rom_count, rom_bytes_total
