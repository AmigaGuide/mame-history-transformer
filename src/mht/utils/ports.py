from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from collections import defaultdict

__all__ = [
    "canonical_port_key",
    "is_valid_port_row",
    "norm_regions",
    "norm_tags",
    "collect_valid_ports_by_category",
    "gh_keys_with_any_valid_ports",
    "build_ports_for_parent",
    "has_parent_clone_duplicate_ports",
    "gh_ids_from_ports_obj",
    "collect_gh_ids_from_ports",
    "render_ports_display",
]

_TERMINAL_PUNCT = ('.', '!', '?', '…')

def _title_case_words(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in (s or "").split())

def _format_models_bracketed(models: List[str] | None) -> str:
    models = [m.strip() for m in (models or []) if isinstance(m, str) and m.strip()]
    return f"[{', '.join(models)}]" if models else ""

def _append_provenance_comment(existing: Optional[str], is_parent_row: bool, machine: str) -> str:
    role = "parent" if is_parent_row else "clone"
    prov = f"This GH port entry is based on the MAME {role} {machine}."
    c = (existing or "").strip()
    if c:
        return f"{c} {prov}" if c.endswith(_TERMINAL_PUNCT) else f"{c}. {prov}"
    return prov

def _date_sort_key(date_str: str, original_index: int) -> Tuple[int, int, int, int]:
    s = (date_str or "").strip()
    y, m, d = "0000", "00", "00"
    parts = s.split("-")
    if len(parts) >= 1 and parts[0]: y = parts[0].replace("X", "0")
    if len(parts) >= 2 and parts[1]: m = parts[1].replace("X", "0")
    if len(parts) >= 3 and parts[2]: d = parts[2].replace("X", "0")
    def _to_int(v: str) -> int:
        try: return int(v)
        except ValueError: return 0
    return (_to_int(y), _to_int(m), _to_int(d), original_index)

# ---------- Normalisers / validators ----------

def is_valid_port_row(row: Dict[str, Any]) -> bool:
    plat = (row or {}).get("platform")
    return isinstance(plat, str) and plat.strip() != ""

def norm_regions(regs: Iterable[str] | None) -> List[str]:
    if not regs:
        return ["??"]
    out = [r.strip() for r in regs if isinstance(r, str) and r.strip()]
    return out or ["??"]

def norm_tags(tags: Iterable[str] | None) -> List[str]:
    return [t.strip() for t in (tags or []) if isinstance(t, str) and t.strip()]

# ---------- Keys / IDs ----------

def canonical_port_key(row: Dict[str, Any]) -> Tuple:
    regions = tuple(r.strip() for r in (row.get("regions") or []) if isinstance(r, str))
    platform = (row.get("platform") or "").strip()
    title    = (row.get("title") or "").strip()
    date     = (row.get("date") or "").strip()
    publisher= (row.get("publisher") or "").strip()
    tags     = tuple(t.strip() for t in (row.get("additional_tags") or []) if isinstance(t, str))
    models   = tuple(m.strip() for m in (row.get("model") or []) if isinstance(m, str))
    comment  = (row.get("comment") or "").strip()
    return (regions, platform, title, date, publisher, tags, models, comment)

def gh_ids_from_ports_obj(ports_obj: Dict[str, Any]) -> List[int]:
    ids: set[int] = set()
    if not isinstance(ports_obj, dict):
        return []
    p = ports_obj.get("parent_source") or {}
    gid = p.get("gh_id")
    if isinstance(gid, int):
        ids.add(gid)
    for cs in (ports_obj.get("clone_sources") or []):
        gid = (cs or {}).get("gh_id")
        if isinstance(gid, int):
            ids.add(gid)
    return sorted(ids)

def collect_gh_ids_from_ports(ports_obj: Dict[str, Any]) -> List[str]:
    if not isinstance(ports_obj, dict):
        return []
    ids = set()
    p = ports_obj.get("parent_source")
    if isinstance(p, dict):
        gid = p.get("gh_id")
        if gid is not None:
            ids.add(gid)
    for c in (ports_obj.get("clone_sources") or []):
        if not isinstance(c, dict):
            continue
        gid = c.get("gh_id")
        if gid is not None:
            ids.add(gid)
    return sorted(ids, key=lambda x: str(x))

# ---------- Collection helpers ----------

def collect_valid_ports_by_category(gh_entry: Dict[str, Any],
                                    source_machine: str,
                                    source_gh_id: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
    cats: Dict[str, List[Dict[str, Any]]] = {}
    ports = (gh_entry or {}).get("ports") or {}
    if not isinstance(ports, dict):
        return cats
    for cat, rows in ports.items():
        if not isinstance(rows, list):
            continue
        out_rows: List[Dict[str, Any]] = []
        for r in rows:
            if not isinstance(r, dict) or not is_valid_port_row(r):
                continue
            out_rows.append({
                "machine":   source_machine,
                "gh_id":     source_gh_id,
                "platform":  r.get("platform"),
                "regions":   norm_regions(r.get("regions")),
                "model":     r.get("model") or [],
                "title":     r.get("title"),
                "date":      r.get("date"),
                "publisher": r.get("publisher"),
                "comment":   r.get("comment"),
                "additional_tags": norm_tags(r.get("additional_tags")),
            })
        if out_rows:
            cats[cat] = out_rows
    return cats

def gh_keys_with_any_valid_ports(gh_ports: Dict[str, Any]) -> set[str]:
    out = set()
    for key, entry in gh_ports.items():
        cats = collect_valid_ports_by_category(entry, key, (entry or {}).get("gh_id"))
        if any(cats.values()):
            out.add(key)
    return out

def build_ports_for_parent(parent: str,
                           parents_map: Dict[str, List[str]],
                           gh_ports: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], set[str], bool]:
    ports_obj: Dict[str, Any] = {"clone_sources": []}
    clones_with_ports: set[str] = set()
    parent_has_ports = False

    p_entry = gh_ports.get(parent)
    if isinstance(p_entry, dict):
        p_cats = collect_valid_ports_by_category(p_entry, parent, p_entry.get("gh_id"))
        if any(p_cats.values()):
            ports_obj["parent_source"] = {
                "machine": parent,
                "gh_id": p_entry.get("gh_id"),
                "categories": p_cats,
            }
            parent_has_ports = True

    for clone in (parents_map.get(parent) or []):
        c_entry = gh_ports.get(clone)
        if not isinstance(c_entry, dict):
            continue
        c_cats = collect_valid_ports_by_category(c_entry, clone, c_entry.get("gh_id"))
        if any(c_cats.values()):
            ports_obj["clone_sources"].append({
                "machine": clone,
                "gh_id": c_entry.get("gh_id"),
                "categories": c_cats,
            })
            clones_with_ports.add(clone)

    if not parent_has_ports and not ports_obj["clone_sources"]:
        return None, clones_with_ports, False
    return ports_obj, clones_with_ports, parent_has_ports

def has_parent_clone_duplicate_ports(ports_obj: Dict[str, Any]) -> bool:
    if not isinstance(ports_obj, dict):
        return False
    p = (ports_obj.get("parent_source") or {}).get("categories") or {}
    clones = [ (cs or {}).get("categories") or {} for cs in (ports_obj.get("clone_sources") or []) ]
    if not p or not clones:
        return False

    parent_sets: Dict[str, set] = {}
    for cat, rows in p.items():
        s = set(canonical_port_key(r) for r in (rows or []))
        if s:
            parent_sets[cat] = s
    if not parent_sets:
        return False

    for cdict in clones:
        for cat, rows in cdict.items():
            if cat not in parent_sets:
                continue
            for r in (rows or []):
                if canonical_port_key(r) in parent_sets[cat]:
                    return True
    return False

# ---------- Rendering ----------

def render_ports_display(parent_machine: str, ports_obj: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Parent+clone rows combined; undated rows shown before dated rows; dates ascending.
    If a category is mixed (parent+clone), we append a provenance sentence to the comment.
    """
    if not isinstance(ports_obj, dict):
        return {}

    out: Dict[str, List[str]] = {}
    cat_roles: Dict[str, set] = {}

    def _scan_source(source: Dict[str, Any], role: str) -> None:
        cats = (source or {}).get("categories") or {}
        for cat_key, rows in cats.items():
            if rows:
                cat_roles.setdefault(cat_key, set()).add(role)

    if ports_obj.get("parent_source"):
        _scan_source(ports_obj["parent_source"], "parent")
    for cs in (ports_obj.get("clone_sources") or []):
        _scan_source(cs, "clone")

    combined: Dict[str, List[Tuple[int, str, Dict[str, Any]]]] = {}
    enc_ix = 0

    def _append_source(source: Dict[str, Any], role: str) -> None:
        nonlocal enc_ix
        cats = (source or {}).get("categories") or {}
        for cat_key, rows in cats.items():
            bucket = combined.setdefault(cat_key, [])
            for r in (rows or []):
                bucket.append((enc_ix, role, r))
                enc_ix += 1

    if ports_obj.get("parent_source"):
        _append_source(ports_obj["parent_source"], "parent")
    for cs in (ports_obj.get("clone_sources") or []):
        _append_source(cs, "clone")

    for cat_key, triples in combined.items():
        disp_cat = _title_case_words(cat_key)
        bucket = out.setdefault(disp_cat, [])

        mixed = (cat_roles.get(cat_key) == {"parent", "clone"})
        undated: List[Tuple[int, str, Dict[str, Any]]] = []
        dated:   List[Tuple[int, str, Dict[str, Any], Tuple[int,int,int,int]]] = []

        for enc, role, r in triples:
            date = (r.get("date") or "").strip()
            if date:
                dated.append((enc, role, r, _date_sort_key(date, enc)))
            else:
                undated.append((enc, role, r))

        dated.sort(key=lambda t: t[3])
        ordered = [ (enc, role, r) for (enc, role, r) in undated ] + \
                  [ (enc, role, r) for (enc, role, r, _) in dated ]

        for enc, role, r in ordered:
            is_parent = (role == "parent")
            regions = "".join(f"[{rgn}]" for rgn in (r.get("regions") or ["??"]))
            platform = (r.get("platform") or "").strip()
            tags = [t.strip() for t in (r.get("additional_tags") or []) if t.strip()]
            tags_seg = f" [{', '.join(tags)}]" if tags else ""
            title = (r.get("title") or "").strip()
            date  = (r.get("date") or "").strip()
            pub   = (r.get("publisher") or "").strip()
            models_in = _format_models_bracketed(r.get("model"))
            machine = (r.get("machine") or "").strip()

            parts: List[str] = []
            parts.append(regions)

            plat_seg = f"{platform}{tags_seg}"
            if title:
                parts.append(plat_seg)
            else:
                parts.append(f"{plat_seg} {models_in}".strip())

            if title:
                safe_title = title.replace('"', '\\"')
                if models_in:
                    parts.append(f"\"{safe_title} {models_in}\"")
                else:
                    parts.append(f"\"{safe_title}\"")

            if date:
                parts.append(f"({date})")
            if pub:
                parts.append(f"by {pub}")

            left = " ".join(p for p in parts if p)
            comment = (r.get("comment") or "").strip()
            if mixed:
                comment = _append_provenance_comment(comment, is_parent_row=is_parent, machine=machine)
            line = f"{left} : {comment}" if comment else left
            bucket.append(line)

    return out

def _format_regions(regs: list[str] | None) -> str:
    regs = regs or ["??"]
    regs = [r.strip() for r in regs if isinstance(r, str) and r.strip()]
    regs = regs or ["??"]
    return "".join(f"[{r}]" for r in regs)

def _format_additional_tags(tags: list[str] | None) -> str:
    tags = [t.strip() for t in (tags or []) if isinstance(t, str) and t.strip()]
    return f" [{', '.join(tags)}]" if tags else ""
