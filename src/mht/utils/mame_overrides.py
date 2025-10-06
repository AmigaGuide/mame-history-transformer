from __future__ import annotations
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
import json

from mht.utils.logger import setup_logger
from mht.utils.titles import find_unbalanced

log = setup_logger()

def load_title_overrides(path: Path) -> dict:
    """
    Load title overrides mapping from JSON file.

    Expected structure:
      {
        "<machine>": {
          "description": "<new description string>",
          "apply_if_unbalanced": true | false,   # default True
          "note": "why/where from"
        },
        ...
      }

    Returns an empty dict on missing file or invalid JSON.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        log.warning("[title_overrides] %s did not contain a JSON object; ignoring.", path)
        return {}
    except FileNotFoundError:
        # Silent: no overrides is normal.
        return {}
    except Exception as e:
        log.warning("[title_overrides] Failed to read %s: %s", path, e)
        return {}


def apply_title_override_if_eligible(
    machine: str,
    original_desc: str,
    overrides: Dict[str, Any],
) -> Tuple[str, Optional[Dict[str, str]], bool]:
    """
    Decide and (optionally) apply a title override for a single machine.

    Returns: (final_description, applied_record_or_None, eligible_flag)

      - final_description: the description to use (overridden or original)
      - applied_record_or_None: if applied, a small audit dict:
            {
              "machine": "<shortname>",
              "from":    "<original_desc>",
              "to":      "<new_desc>",
              "reason":  "<note or 'override'>"
            }
        else None.
      - eligible_flag: True if an override existed *and* its condition
        (“apply only if unbalanced”, unless explicitly disabled) was met.

    Rules:
      - If no override for this machine, return (original, None, False).
      - If override exists:
          * apply_if_unbalanced (default True):
              - When True -> only eligible if original_desc is unbalanced
                in either () or [] brackets.
              - When False -> always eligible.
          * If eligible and "description" is a non-empty string, apply it.
    """
    ov = overrides.get(machine)
    if not isinstance(ov, dict):
        return original_desc, None, False

    apply_if_unbalanced = bool(ov.get("apply_if_unbalanced", True))
    if apply_if_unbalanced:
        unb_round, unb_square = find_unbalanced(original_desc or "")
        condition_met = bool(unb_round or unb_square)
    else:
        condition_met = True

    if not condition_met:
        # Override exists but not eligible given the rule.
        return original_desc, None, False

    new_desc = ov.get("description")
    if isinstance(new_desc, str) and new_desc.strip():
        applied_record = {
            "machine": machine,
            "from": original_desc,
            "to": new_desc.strip(),
            "reason": str(ov.get("note") or "override"),
        }
        return new_desc.strip(), applied_record, True

    # Eligible, but nothing to apply (e.g., description missing/blank)
    return original_desc, None, True


def dedupe_anomalies_preferring_pre_override(
    anoms: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Deduplicate anomaly rows by (machine, example), preferring any record with
    pre_override=True when both pre/post copies exist.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cat, items in (anoms or {}).items():
        seen: Dict[tuple, Dict[str, Any]] = {}
        for it in items or []:
            key = (it.get("machine"), it.get("example"))
            prev = seen.get(key)
            if prev is None:
                seen[key] = it
            else:
                if it.get("pre_override") and not prev.get("pre_override"):
                    seen[key] = it
        out[cat] = list(seen.values())
    return out
