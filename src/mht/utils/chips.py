from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional, Tuple, List, Dict, Any

__all__ = [
    "hz_to_human",
    "format_hz_3dp",
    "_chip_label",
    "_prefix_multiples",
    "sum_device_speakers",
    "_has_samples_flag",
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


def _chip_label(name: Optional[str], clock_hz: Any) -> str:
    """
    Build a human-readable chip label, e.g. 'Z80 @ 3.579 MHz'.
    If frequency can't be normalised, returns just the name.
    """
    nm = (name or "").strip()
    human = hz_to_human(clock_hz)
    return f"{nm} @ {human[0]:.3f} {human[1]}" if human else nm


def _prefix_multiples(labels: Iterable[str]) -> List[str]:
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


def _has_samples_flag(device_ref: Any) -> bool:
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


def build_chips_section(
    chips: Optional[List[Dict[str, Any]]],
    sound_channels: Optional[int],
    device_ref: Any,
) -> Dict[str, Any]:
    """
    Build the structured 'chips' section used by the transformer.

    Returns:
    {
      "cpus":        {"heading": "CPU|CPUs", "count": int, "items": [str, ...]},
      "audio_chips": {"heading": "Audio Chip|Audio Chips", "count": int, "items": [str, ...]},
      "requires_samples": bool,
      "audio_channels": int,
      "speakers": int,
    }
    """
    cpu_labels_raw: List[str] = []
    audio_chip_labels_raw: List[str] = []
    speaker_count = 0

    for ch in (chips or []):
        typ = (ch.get("type") or "").strip().lower()
        name_raw = (ch.get("name") or "").strip()
        clk = ch.get("clock_hz")
        name_ci = name_raw.casefold()

        if typ == "cpu":
            cpu_labels_raw.append(_chip_label(name_raw, clk))
            continue

        if typ == "audio":
            # treat 'speaker' as a device, not an audio chip label
            if name_ci == "speaker":
                speaker_count += 1
                continue
            # ignore 'samples' pseudo-device lines
            if name_ci in {"samples", "sample"}:
                continue
            audio_chip_labels_raw.append(_chip_label(name_raw, clk))
            continue

    cpu_items   = _prefix_multiples(cpu_labels_raw)
    audio_items = _prefix_multiples(audio_chip_labels_raw)

    cpu_heading   = "CPU" if len(cpu_labels_raw) == 1 else "CPUs"
    audio_heading = "Audio Chip" if len(audio_chip_labels_raw) == 1 else "Audio Chips"

    # Normalise channels to an int
    try:
        chn = int(sound_channels) if sound_channels is not None else 0
    except Exception:
        chn = 0

    requires_samples = _has_samples_flag(device_ref)

    return {
        "cpus": {
            "heading": cpu_heading,
            "count": len(cpu_labels_raw),
            "items": cpu_items,
        },
        "audio_chips": {
            "heading": audio_heading,
            "count": len(audio_chip_labels_raw),
            "items": audio_items,
        },
        "requires_samples": bool(requires_samples),
        "audio_channels": chn,
        "speakers": int(speaker_count),
    }


def render_chips_display(
    chips_raw: dict,
    requires_samples: bool = False,
    sound_channels: Optional[int] = None,
    speaker_count: Optional[int] = None,
) -> Dict[str, List[str]]:
    """
    Build the 'chips_display' structure used by the wiki/raw projections.

    Expects chips_raw in the shape produced by build_chips_section():
      {
        "cpus": {"heading": "...", "count": N, "items": [label, ...]},
        "audio_chips": {"heading": "...", "count": M, "items": [label, ...]},
        "requires_samples": bool,
        "audio_channels": int,
        "speakers": int,
      }

    The result:
      {
        "cpus": [ "...", ... ],
        "audio_chips": [ "...", ..., "Requires additional samples", "Audio Channels: X", "Speakers: Y" ]
      }
    """
    def _rows(section):
        if isinstance(section, dict):
            return section.get("items") or []
        return section or []

    def _norm_rows(rows):
        for r in rows or []:
            if isinstance(r, dict):
                name = (r.get("name") or "").strip()
                clk  = r.get("clock_hz")
            elif isinstance(r, str):
                # Accept pre-rendered strings (already labelled)
                yield r
                continue
            else:
                continue

            if not name:
                continue

            # Recreate the compact label formatting used elsewhere
            h = hz_to_human(clk)
            label = f"{name} @ {h[0]:.3f} {h[1]}" if h else name
            yield label

    def _group_and_render(labels: List[str]) -> List[str]:
        # Collapse duplicates case-insensitively; preserve first-seen order
        from collections import Counter
        counts = Counter(l.casefold() for l in labels)
        first_seen = []
        seen = set()
        for l in labels:
            k = l.casefold()
            if k not in seen:
                seen.add(k)
                first_seen.append(l)
        out = []
        for l in first_seen:
            n = counts[l.casefold()]
            out.append(f"({n}x) {l}" if n > 1 else l)
        return out

    # Source rows (either structured dicts or already-rendered strings)
    cpu_src   = list(_norm_rows(_rows((chips_raw or {}).get("cpus"))))
    audio_all = list(_norm_rows(_rows((chips_raw or {}).get("audio_chips"))))

    # Filter out speaker/samples if they accidentally leak in as chip labels
    audio_filtered = [l for l in audio_all if l.lower() not in {"speaker", "samples"}]

    out = {
        "cpus": _group_and_render(cpu_src),
        "audio_chips": _group_and_render(audio_filtered),
    }

    # Tail lines
    tail: List[str] = []
    if requires_samples:
        tail.append("Requires additional samples")

    if sound_channels is not None:
        try:
            n = int(sound_channels)
        except Exception:
            n = 0
        tail.append(f"Audio {'Channel' if n == 1 else 'Channels'}: {n}")

    if speaker_count is None:
        # If not provided, try to infer from chips_raw if it used the structured shape
        try:
            inferred = int((chips_raw or {}).get("speakers", 0))
        except Exception:
            inferred = 0
        speaker_count = inferred

    try:
        nsp = int(speaker_count or 0)
    except Exception:
        nsp = 0
    tail.append(f"{'Speaker' if nsp == 1 else 'Speakers'}: {nsp}")

    if tail:
        out["audio_chips"].extend(tail)

    return out
