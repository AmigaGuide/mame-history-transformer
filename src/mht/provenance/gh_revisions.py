"""Read-only discovery of the advertised Gaming History archive revision.

This module does not use the Gaming History API, download ZIPs, or change releases.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re

import requests

from mht.utils.paths import active_version, archives_dir

GH_DOWNLOAD_PAGE = "https://www.arcade-history.com/index.php?page=download"
_VERSION_RE = re.compile(r"(?<![\w.])(?:v|ver(?:sion)?\.?)\s*(\d+)\.(\d{2,3})([a-z]?)(?![\w.])", re.I)
_FILENAME_RE = re.compile(r"^history(\d{3,4})([a-z]?)\.zip$", re.I)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("div", "p", "h1", "h2", "h3", "li", "a", "section"):
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _parse_version(text: str) -> tuple[str, str] | None:
    m = _VERSION_RE.search(text)
    if not m:
        return None
    major, minor, suffix = m.groups()
    # GH v2.89 belongs to MAME 0.289, and v3.00 to 0.300.
    if len(minor) != 2:
        return None
    return f"{int(major) * 100 + int(minor):04d}", suffix.lower()


def advertised_history(html: str) -> dict[str, str]:
    """Identify the *latest* advertised release, not an older release in a list.

    Both 'Latest version v2.89a' and legacy 'Download Ver. 2.89a' pages
    are recognised. Fail closed if the page lacks either context.
    """
    parser = _VisibleText()
    parser.feed(html)
    text = " ".join("".join(parser.parts).split())
    match = re.search(r"\bLatest\s+version\b", text, re.I)
    if match:
        candidate = _parse_version(text[match.end():match.end() + 180])
    else:
        match = re.search(r"\bDownload\s+Ver\.?\s*", text, re.I)
        candidate = _parse_version("v" + text[match.end():match.end() + 25]) if match else None
    if not candidate:
        raise ValueError("Could not identify the latest Gaming History version on the official download page")
    release, suffix = candidate
    return {"release": release, "revision": suffix, "filename": f"history{int(release)}{suffix}.zip"}


def _revision_key(suffix: str) -> int:
    return 0 if not suffix else ord(suffix) - ord("a") + 1


def staged_history(release: str, *, directory: Path | None = None) -> dict[str, str] | None:
    """Return the highest recognised staged archive; no ZIP contents are read."""
    if not re.fullmatch(r"\d{4}", release):
        raise ValueError("Release must be a four-digit MHT release key, such as 0289")
    folder = directory if directory is not None else archives_dir(release)
    candidates = []
    if folder.is_dir():
        for path in folder.iterdir():
            if not path.is_file():
                continue
            m = _FILENAME_RE.fullmatch(path.name)
            if m and f"{int(m.group(1)):04d}" == release:
                candidates.append((_revision_key(m.group(2).lower()), path.name, m.group(2).lower()))
    if not candidates:
        return None
    _, name, suffix = max(candidates)
    return {"filename": name, "revision": suffix}


def check_gh_revision(release: str | None = None, *, timeout: float = 15.0,
                      session=None, directory: Path | None = None) -> dict:
    """Check the official public HTML and local archive names, without writing data.

    An archive being staged does not prove the ZIP is valid or that stages used it.
    """
    target = release if release is not None else active_version()
    if not re.fullmatch(r"\d{4}", target):
        raise ValueError("Release must be a four-digit MHT release key, such as 0289")
    local = staged_history(target, directory=directory)
    get = session.get if session is not None else requests.get
    response = get(GH_DOWNLOAD_PAGE, timeout=timeout)
    response.raise_for_status()
    advertised = advertised_history(response.text)
    remote_release = advertised["release"]
    if int(remote_release) < int(target):
        status = "website_older"
    elif int(remote_release) > int(target):
        status = "different_release"
    elif local is None:
        status = "not_staged"
    elif _revision_key(advertised["revision"]) > _revision_key(local["revision"]):
        status = "update_available"
    elif _revision_key(advertised["revision"]) == _revision_key(local["revision"]):
        status = "up_to_date"
    else:
        status = "local_newer"
    return {"release": target, "staged": local, "advertised": advertised,
            "status": status, "source": GH_DOWNLOAD_PAGE}
