"""
Deprecated shim: re-export title parsing from mht.utils.titles.
Keep until all imports use mht.utils.titles.
"""
from mht.utils.titles import (
    parse_description as parse_description,
    find_unbalanced   as find_unbalanced,
    # Provide the underscored legacy aliases too:
    parse_description as _parse_description,
    find_unbalanced   as _find_unbalanced,
)

__all__ = [
    "parse_description", "find_unbalanced",
    "_parse_description", "_find_unbalanced",
]
