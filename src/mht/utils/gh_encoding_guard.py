"""Read-only preflight for selected Gaming History parsing stages.

Reject a cache that describes a different archive/member, before any stage
outputs or stamps are touched. Missing optional INIs are allowed.
"""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from mht.utils.paths import encodings_cache_path

_HISTORY_XML = 'history.xml'
_INI_NAMES = (
    '[GAMING HISTORY] Game Or No Game.ini',
    '[GAMING HISTORY] Machine Category.ini',
    '[GAMING HISTORY] Machine Type.ini',
)


def check_gh_encoding_cache(
    version: str, archive: Path, stage: str, *, cache_path: Path | None = None
) -> None:
    """Raise ValueError if GH encoding provenance does not match ZIP members.

    No writes and no fallback to inferred/default encodings are permitted.
    """
    if stage not in ('history', 'ini'):
        raise ValueError(f'Unsupported GH stage: {stage}')
    path = Path(cache_path) if cache_path is not None else encodings_cache_path(version)
    try:
        cache = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f'Cannot read encoding cache {path}: {exc}') from exc
    if not isinstance(cache, dict):
        raise ValueError(f'Invalid encoding cache {path}: expected object')

    try:
        with ZipFile(archive) as zf:
            members = {}
            for info in zf.infolist():
                if info.is_dir():
                    continue
                key = Path(info.filename).name.lower()
                if key in members:
                    raise ValueError(f'Ambiguous ZIP members sharing basename {key}: {archive.name}')
                members[key] = info
    except (OSError, BadZipFile) as exc:
        raise ValueError(f'Cannot inspect GH archive {archive}: {exc}') from exc

    wanted = (_HISTORY_XML,) if stage == 'history' else _INI_NAMES
    for leaf in wanted:
        member = members.get(leaf.lower())
        record = cache.get(leaf)
        if member is None:
            if leaf == _HISTORY_XML:
                raise ValueError(f'Missing history.xml in {archive.name}')
            if record is not None:
                raise ValueError(f'Encoding cache still records absent INI {leaf}')
            continue  # GH may legitimately omit a particular INI
        if not isinstance(record, dict):
            raise ValueError(f'Missing encoding provenance for {leaf}')
        signature = {
            'zip_archive': archive.name,
            'zip_member': member.filename,
            'zip_crc32': member.CRC,
            'zip_size_bytes': member.file_size,
        }
        for key, expected in signature.items():
            if record.get(key) != expected:
                raise ValueError(
                    f'Stale encoding provenance for {leaf}: {key} '
                    f'is {record.get(key)!r}, expected {expected!r}'
                )
        if not isinstance(record.get('encoding'), str) or not record['encoding'].strip():
            raise ValueError(f'Missing detected encoding for {leaf}')
