"""
Resolve release-matched progetto-SNAPS download links.

This module does not perform network requests or downloads.
It examines HTML supplied by the caller and returns a source
only when the advertised archive matches the requested release.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse


SITE_URL = "https://www.progettosnaps.net/"
SUPPORT_URL = urljoin(SITE_URL, "support/")
CATVER_URL = urljoin(SITE_URL, "catver/")

_ARCHIVE_RE = re.compile(
    r"^pS_(CatVer|SupportFiles)_(\d{3})\.zip$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SnapsSource:
    release: str
    package_type: str
    filename: str
    url: str


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return

        attributes = dict(attrs)
        href = attributes.get("href")

        if href:
            self.hrefs.append(href)


def _candidates(html: str, page_url: str):
    parser = _Links()
    parser.feed(html)

    for href in parser.hrefs:
        url = urljoin(page_url, href)
        parsed = urlparse(url)

        if parsed.scheme != "https":
            continue

        if parsed.hostname not in (
            "progettosnaps.net",
            "www.progettosnaps.net",
        ):
            continue

        if parsed.path.rstrip("/") != "/download":
            continue

        query = parse_qs(parsed.query)
        file_values = query.get("file", [])
        types = query.get("tipo", [])

        if len(file_values) != 1 or len(types) != 1:
            continue

        filename = PurePosixPath(
            unquote(file_values[0]).replace("\\", "/")
        ).name

        match = _ARCHIVE_RE.fullmatch(filename)
        if not match:
            continue

        package_type = match.group(1).lower()
        release = "0" + match.group(2)

        expected_type = (
            "catver" if package_type == "catver"
            else "support_pack"
        )

        if types[0].lower() != expected_type:
            continue

        yield SnapsSource(
            release=release,
            package_type=package_type,
            filename=filename,
            url=url,
        )


def resolve_snaps_source(
    release: str,
    *,
    support_html: str,
    catver_html: str,
) -> SnapsSource | None:
    """
    Prefer an advertised, release-matched CatVer package.

    Fall back to an advertised historical SupportFiles pack.

    Never substitute the newest release for a missing version.
    """
    if not re.fullmatch(r"0\d{3}", release):
        raise ValueError(f"Invalid MAME release: {release}")

    sources = [
        *_candidates(catver_html, CATVER_URL),
        *_candidates(support_html, SUPPORT_URL),
    ]

    for package_type in ("catver", "supportfiles"):
        unique = {}

        for source in sources:
            if (
                source.release == release
                and source.package_type == package_type
            ):
                unique[source.url] = source

        matches = list(unique.values())

        # The SupportFiles page can advertise the same release
        # in both its current and historical pack directories.
        if package_type == "supportfiles" and len(matches) > 1:
            current = [
                source for source in matches
                if (
                    urlparse(source.url).path.rstrip("/")
                    == "/download"
                    and parse_qs(
                        urlparse(source.url).query
                    ).get("file") == [
                        f"/support/packs/{source.filename}"
                    ]
                )
            ]

            if len(current) == 1:
                return current[0]

        if len(matches) > 1:
            raise ValueError(
                f"Multiple {package_type} sources for {release}"
            )

        if matches:
            return matches[0]

    return None
