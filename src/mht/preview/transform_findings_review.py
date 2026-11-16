"""Read-only examination of retained Transformation findings.

Do not infer missing navigation details or change publication decisions.
"""
from __future__ import annotations

PAGE_SIZE = 50
NAV_KEYS = (
    ('page_name_collisions', 'Page-name collisions'),
    ('redirect_conflicts', 'Redirect conflicts'),
    ('redirect_page_collisions', 'Redirect/page collisions'),
)


def _map(value):
    return value if isinstance(value, dict) else {}


def _count(value):
    return value if type(value) is int and value >= 0 else None


def build_transform_findings_review(summary, *, preview_machines=(), query='', kind='', page='1'):
    """Return bounded per-record title and PORTS findings with source provenance."""
    summary = _map(summary)
    available = set(preview_machines) if isinstance(preview_machines, (list, tuple, set)) else set()
    rows = []
    title_groups = _map(summary.get('title_anomalies'))
    for category, entries in sorted(title_groups.items(), key=lambda item: str(item[0]).casefold()):
        if not isinstance(category, str) or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            machine = entry.get('machine')
            machine = machine if isinstance(machine, str) and machine.strip() else None
            example = entry.get('example')
            example = example if isinstance(example, str) else None
            if machine is None and example is None:
                continue
            rows.append({'kind': 'title', 'category': category, 'machine': machine,
                         'evidence': example, 'pre_override': entry.get('pre_override') is True,
                         'preview': machine in available if machine else False})
    ports = _map(_map(summary.get('ports')).get('parent_clone_duplicate_ports'))
    machines = ports.get('systems_list')
    if isinstance(machines, list):
        for machine in machines:
            if isinstance(machine, str) and machine.strip():
                rows.append({'kind': 'ports', 'category': 'Parent/clone PORTS duplication',
                             'machine': machine, 'evidence': None, 'pre_override': False,
                             'preview': machine in available})
    kinds = {'title', 'ports'}
    kind = kind if kind in kinds else ''
    query = query.strip()[:120] if isinstance(query, str) else ''
    filtered = [r for r in rows if (not kind or kind == r['kind'])
                and (not query or any(query.casefold() in str(v).casefold()
                    for v in (r['machine'] or '', r['category'], r['evidence'] or '')))]
    try:
        page_num = int(page)
    except (TypeError, ValueError):
        page_num = 1
    pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    page_num = max(1, min(page_num, pages))
    offset = (page_num - 1) * PAGE_SIZE
    navigation = _map(summary.get('wiki_navigation'))
    navigation_rows = [{'label': label, 'path': f'wiki_navigation.{key}', 'count': _count(navigation.get(key))}
                       for key, label in NAV_KEYS]
    return {
        'rows': filtered[offset:offset + PAGE_SIZE], 'total': len(filtered),
        'all_records': len(rows), 'title_records': sum(r['kind'] == 'title' for r in rows),
        'ports_records': sum(r['kind'] == 'ports' for r in rows),
        'recorded_ports_total': _count(ports.get('systems_count')),
        'recorded_title_counts': {k: v for k, v in _map(summary.get('title_anomaly_counts')).items()
                                  if isinstance(k, str) and _count(v) is not None},
        'navigation_rows': navigation_rows,
        'navigation_total': _count(navigation.get('conflicts_total')),
        'q': query, 'kind': kind, 'page': page_num, 'pages': pages,
    }


def build_machine_transform_findings(summary, machine):
    """Retain just a machine's source-backed records, capped for page rendering."""
    if not isinstance(machine, str):
        return []
    # Use original summary to avoid the page-length cap on aggregate review.
    summary = _map(summary)
    result = []
    for category, entries in _map(summary.get('title_anomalies')).items():
        if not isinstance(category, str) or not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, dict) and item.get('machine') == machine:
                example = item.get('example')
                if isinstance(example, str):
                    result.append({'label': category, 'detail': example, 'path': 'title_anomalies'})
    ports = _map(_map(summary.get('ports')).get('parent_clone_duplicate_ports'))
    if machine in ports.get('systems_list', []) if isinstance(ports.get('systems_list'), list) else False:
        result.append({'label': 'Parent/clone PORTS duplication', 'detail': None,
                       'path': 'ports.parent_clone_duplicate_ports.systems_list'})
    return result[:30]
