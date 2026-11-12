"""Human-readable, read-only differences between generated GH Trivia sections.

This is a diagnostic rendering layer, not a parser or Wiki synchroniser.
It shares the Trivia comparator's projection of rendered block fields, so
provenance, source text and parser metadata cannot create false differences.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from mht.audit.trivia_diff import _read_trivia, _rendered_blocks


def _block_text(block: tuple[Any, ...]) -> str:
    kind = block[0]
    if kind in ("paragraph", "subheading"):
        return str(block[1])
    if kind == "pair":
        return f"{block[1]}: {block[2]}"
    if kind in ("bullet_list", "numbered_list"):
        return " | ".join(str(item) for item in block[1])
    raise ValueError(f"Unsupported Trivia block type: {kind!r}")


def _snippet(text: str, start: int, end: int, context: int = 55) -> str:
    """Keep the changed area and limited context rather than entire essays."""
    left = max(0, start - context)
    right = min(len(text), end + context)
    segment = text[left:right].replace("\n", " ")
    return ("..." if left else "") + segment + ("..." if right < len(text) else "")


def _changed_text(before: str, after: str) -> tuple[str, str]:
    """Extract the minimal differing span with nearby unchanged context."""
    matcher = SequenceMatcher(None, before, after, autojunk=False)
    changes = [(a0, a1, b0, b1) for op, a0, a1, b0, b1 in matcher.get_opcodes()
               if op != "equal"]
    if not changes:
        return before, after
    a_start, a_end = changes[0][0], changes[-1][1]
    b_start, b_end = changes[0][2], changes[-1][3]
    return _snippet(before, a_start, a_end), _snippet(after, b_start, b_end)


def _render_block(prefix: str, block: tuple[Any, ...], text: str | None = None) -> str:
    return f"  {prefix} [{block[0]}] {_block_text(block) if text is None else text}"


def detail_for_machine(
    before_version: str,
    after_version: str,
    machine: str,
    *,
    before_data: dict[str, Any] | None = None,
    after_data: dict[str, Any] | None = None,
) -> str:
    """Return readable changed GH Trivia blocks for one machine.

    Both datasets can be provided to avoid repeated disk reads when reporting
    many machines. Empty string means no changes in rendered Trivia blocks.
    """
    if before_data is None:
        before_data = _read_trivia(before_version)
    if after_data is None:
        after_data = _read_trivia(after_version)

    before_record = before_data.get(machine)
    after_record = after_data.get(machine)
    for version, record in ((before_version, before_record), (after_version, after_record)):
        if record is not None and not isinstance(record, dict):
            raise ValueError(f"Invalid Trivia record for {machine!r} in {version}")

    old = _rendered_blocks(before_record)
    new = _rendered_blocks(after_record)
    changed_sections = sorted(name for name in old.keys() | new.keys()
                              if old.get(name, []) != new.get(name, []))
    if not changed_sections:
        return ""

    lines = [f"{machine} - GH Trivia changes ({before_version} -> {after_version})"]
    for section in changed_sections:
        previous = old.get(section, [])
        current = new.get(section, [])
        if not previous:
            state = "SECTION ADDED"
        elif not current:
            state = "SECTION REMOVED"
        else:
            state = "SECTION MODIFIED"
        lines.append(f"\n  {section.upper()} - {state}")
        matcher = SequenceMatcher(None, previous, current, autojunk=False)
        for operation, i1, i2, j1, j2 in matcher.get_opcodes():
            if operation == "equal":
                continue
            old_segment = previous[i1:i2]
            new_segment = current[j1:j2]
            if operation == "replace":
                # Pair same-kind replacements to show a compact changed span.
                # Remaining unmatched blocks are shown as removals/additions.
                paired = min(len(old_segment), len(new_segment))
                for index in range(paired):
                    old_block, new_block = old_segment[index], new_segment[index]
                    if old_block[0] == new_block[0]:
                        old_text, new_text = _changed_text(
                            _block_text(old_block), _block_text(new_block)
                        )
                        lines.append(_render_block("-", old_block, old_text))
                        lines.append(_render_block("+", new_block, new_text))
                    else:
                        lines.append(_render_block("-", old_block))
                        lines.append(_render_block("+", new_block))
                old_segment = old_segment[paired:]
                new_segment = new_segment[paired:]
            for block in old_segment:
                lines.append(_render_block("-", block))
            for block in new_segment:
                lines.append(_render_block("+", block))
    return "\n".join(lines)


def format_trivia_details(
    before_version: str,
    after_version: str,
    machines: list[str] | set[str],
) -> str:
    """Format changed Trivia for specified machines; read datasets once each."""
    old = _read_trivia(before_version)
    new = _read_trivia(after_version)
    rendered = [detail_for_machine(before_version, after_version, machine,
                                  before_data=old, after_data=new)
                for machine in sorted(set(machines))]
    return "\n\n".join(part for part in rendered if part)
