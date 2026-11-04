"""
Build complete introductory sentences for ExoticA LiT wiki pages.

Gameplay descriptions come from the reviewed PS-SNAPS vocabulary.
Technical modifiers come from MAME metadata.

The web preview must display the finished sentence unchanged.
"""

from __future__ import annotations


def build_opening_sentence(
    *,
    title: str,
    genre_phrase: str,
    year: str | None = None,
    manufacturer: str | None = None,
    laserdisc: bool = False,
    vector: bool = False,
) -> str:
    """Construct a wiki-ready opening sentence from approved information."""

    title = (title or "").strip()
    phrase = (genre_phrase or "").strip()
    year = (year or "").strip()
    manufacturer = (manufacturer or "").strip()

    if not title:
        raise ValueError("Opening sentence requires a game title.")

    if not phrase.startswith(("a ", "an ")):
        raise ValueError(
            "Opening sentence requires an approved genre phrase "
            "beginning with 'a' or 'an'."
        )

    # LaserDisc games receive the historically appropriate modifier.
    if laserdisc:
        article, description = phrase.split(" ", 1)
        phrase = f"an interactive {description}"

    # Vector graphics are a technical characteristic, not a genre.
    if vector:
        phrase += " featuring vector graphics"

    sentence = f"{title} is {phrase}"

    if year and manufacturer:
        publication = f"published in {year} by {manufacturer}"
    elif year:
        publication = f"published in {year}"
    elif manufacturer:
        publication = f"published by {manufacturer}"
    else:
        publication = ""

    if publication:
        separator = ", " if vector else " "
        sentence += separator + publication

    return sentence + "."
