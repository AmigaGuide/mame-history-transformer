from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional, Tuple, List, Dict, Any


__all__ = [
    "hz_to_human",
    "format_hz_3dp",
    "chip_label",
    "prefix_multiples",
    "sum_device_speakers",
    "has_samples_flag",
]


def hz_to_human(n: int | float | None) -> Optional[Tuple[float, str]]:
    """
    Convert a frequency in Hz to a (value, unit) pair using binary prefixes:
      - >= 1e9 -> GHz
      - >= 1e6 -> MHz
      - >= 1e3 -> kHz
      - else    -> Hz (if >= 1.0)
    Returns None for None/invalid/<=0 values and for 0 < n < 1 (to match existing behaviour).
    """
    if n is None:
        return None
    try:
        v = float(n)
    except (TypeError, ValueError):
        return None
    if v < 1.0:
        return None

    GHz = 1_000_000_000.0
    MHz = 1_000_000.0
    kHz = 1_000.0

    if v >= GHz:
        return (v / GHz, "GHz")
    if v >= MHz:
        return (v / MHz, "MHz")
    if v >= kHz:
        return (v / kHz, "kHz")
    return (v, "Hz")


def format_hz_3dp(hz: Any) -> Optional[str]:
    """
    Format a raw Hz value as '<value> Hz' with 3 decimal places.
    Returns None for invalid/<=0 inputs.
    """
    try:
        v = float(hz)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return f"{v:.3f} Hz"


def chip_label(name: Optional[str], clock_hz: Any) -> str:
    """
    Build a human-readable chip label, e.g. 'Z80 @ 3.579 MHz'.
    If frequency can't be normalised, returns just the name.
    """
    nm = (name or "").strip()
    human = hz_to_human(clock_hz)
    return f"{nm} @ {human[0]:.3f} {human[1]}" if human else nm


def prefix_multiples(labels: Iterable[str]) -> List[str]:
    """
    Collapse identical labels (case-insensitive), preserving first-seen order,
    and prefix counts in '(Nx) ' form for duplicates.
    """
    labels = [l for l in (labels or []) if l]
    counts = Counter(l.casefold() for l in labels)
    first_seen_unique = list(dict.fromkeys(labels))  # preserves order
    out: List[str] = []
    for lab in first_seen_unique:
        n = counts[lab.casefold()]
        out.append(f"({n}x) {lab}" if n > 1 else lab)
    return out


def sum_device_speakers(device_ref: Any) -> int:
    """
    Sum speaker references from a device_ref list like:
      [{"samples": "yes"/"no", "speaker": <int>}, ...]
    Non-integer/absent values are treated as 0.
    """
    if not isinstance(device_ref, (list, tuple)):
        return 0
    total = 0
    for d in device_ref:
        try:
            total += int((d or {}).get("speaker", 0))
        except Exception:
            # Ignore individual bad entries
            continue
    return total


def has_samples_flag(device_ref: Any) -> bool:
    """
    Return True if any device_ref entry signals samples are required.
    Accepts 'yes/true/1/y' (case-insensitive) in the 'samples' field.
    """
    if not isinstance(device_ref, (list, tuple)):
        return False
    for d in device_ref:
        s = str((d or {}).get("samples", "")).strip().lower()
        if s in {"yes", "true", "1", "y"}:
            return True
    return False
