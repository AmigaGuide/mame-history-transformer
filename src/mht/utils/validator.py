from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable, Tuple, Dict
from jsonschema import Draft202012Validator

from mht.utils.paths import (
    # output docs
    EXOTICA_RAW,
    EXOTICA_WIKI,
    EXOTICA_PAGES,
    # schemas
    EXOTICA_RAW_SCHEMA,
    EXOTICA_WIKI_SCHEMA,
    EXOTICA_PAGES_SCHEMA,
)

# One source of truth for (schema, document) pairs
REGISTRY: Dict[str, Tuple[Path, Path]] = {
    "raw":   (EXOTICA_RAW_SCHEMA,   EXOTICA_RAW),
    "wiki":  (EXOTICA_WIKI_SCHEMA,  EXOTICA_WIKI),
    "pages": (EXOTICA_PAGES_SCHEMA, EXOTICA_PAGES),
}

def validate(names: Iterable[str] | None = None) -> list[str]:
    """
    Validate one or more output JSON documents against their JSON Schemas.

    Parameters
    ----------
    only
        Optional subset of keys from VALIDATION_REGISTRY to validate.

    Returns
    -------
    list[str]
        Human-readable error lines; empty list means 'Validation OK'.
    """
    targets = (names or REGISTRY.keys())
    errors_out: list[str] = []

    for name in targets:
        if name not in REGISTRY:
            errors_out.append(f"[{name}] unknown target")
            continue

        schema_path, doc_path = REGISTRY[name]
        if not schema_path.exists():
            errors_out.append(f"[{name}] missing schema: {schema_path}")
            continue
        if not doc_path.exists():
            errors_out.append(f"[{name}] missing document: {doc_path}")
            continue

        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            doc    = json.loads(doc_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors_out.append(f"[{name}] read error: {e}")
            continue

        v = Draft202012Validator(schema)
        problems = list(v.iter_errors(doc))
        if problems:
            for e in sorted(problems, key=lambda e: (list(e.path), e.message)):
                path_str = "/".join(map(str, e.path)) or "(root)"
                errors_out.append(f"[{name}] /{path_str} -> {e.message}")

    return errors_out
