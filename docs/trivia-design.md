# TRIVIA Parsing Design (v1)

## Status
- Scope agreed; implementation pending.
- Applies to `<system><text>` content excluding `PORTS` and `CONTRIBUTE`.

## Goals & Non-goals
- **Goals:** Deterministic capture of sections (`overview`, `technical`, `trivia`, `updates`, `scoring`, `tips_and_tricks`, `series`, `staff`), with block typing for downstream use.
- **Non-goals (v1):** Table extraction (>2 columns), quote attribution, cross-system merge (e.g. puckman/pacman).

## Section Tags
`overview`, `technical`, `trivia`, `updates`, `scoring`, `tips_and_tricks`, `series`, `staff`.

## Block Types
`paragraph`, `bullets`, `numbered`, `pairs`, `lead_with_bullets`, `lead_with_numbered`, `subheading`, `unknown`.

## Recognition Rules (succinct)
- **Heading:** `- HEADING -` → start section.
- **Subheading:** `^\*\s+(.+?)\s*:\s*$` → `{"type":"subheading","title":"…","blocks":[]}`.
- **Unled bullet:** `^\*\s+.+$` (not colon-terminated) → `bullets`.
- **Hyphen/• bullet:** `^\s*[\-•]\s+.+$` → `bullets`.
- **Led bullets:** previous non-blank line ends with `:` and current line is not numbered → `lead_with_bullets`.
- **Numbered:** `^\s*(?:\d+[.)]|\[\d+\])\s+.+$`. If preceded by a colon lead → `lead_with_numbered`.
- **Pairs:** `^(.+?)\s*-\s*(.+)$` or `^(.+?)\s*:\s*(.+)$` → `pairs`.
- **Paragraph:** any other non-empty line.
- **Blank line:** closes current block.
- Decode HTML entities before classification.

## Suppression
Use `"suppressed": true, "reason": "<why>"`.
- `overview` boilerplate (e.g. “Arcade Video game published …”, “Title (c) YEAR …”) → `boilerplate_opening`.
- `technical` duplicates of MAME fields (CPUs, sound chips, players, controls) → `duplicate_of_mame`.
- Future: soundtrack dumps → `soundtrack_out_of_scope`.

## JSON Shape (per system)
```json
{
  "sections": {
    "overview": { "blocks": [], "summary": { "blocks_total": 0, "suppressed_blocks": 0 } },
    "technical": { "blocks": [], "summary": { "blocks_total": 0, "suppressed_blocks": 0 } },
    "trivia": { "blocks": [], "summary": { "blocks_total": 0, "suppressed_blocks": 0 } },
    "updates": { "blocks": [], "summary": { "blocks_total": 0, "suppressed_blocks": 0 } },
    "scoring": { "blocks": [], "summary": { "blocks_total": 0, "suppressed_blocks": 0 } },
    "tips_and_tricks": { "blocks": [], "summary": { "blocks_total": 0, "suppressed_blocks": 0 } },
    "series": { "blocks": [], "summary": { "blocks_total": 0, "suppressed_blocks": 0 } },
    "staff": { "blocks": [], "summary": { "blocks_total": 0, "suppressed_blocks": 0 } }
  }
}
