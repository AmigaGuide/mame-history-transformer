import json


def test_bidirectional_consistency(outputs_dir):
    DOC = (outputs_dir / "mame_parent_index.json")
    d = json.loads(DOC.read_text(encoding="utf-8"))
    parents = d["parents"]
    c2p = d["child_to_parent"]

    # 1) Every clone listed under a parent maps back to that parent
    for p, clones in parents.items():
        for c in clones:
            assert c in c2p, f"{c} missing in child_to_parent"
            assert c2p[c] == p, f"{c}: child_to_parent={c2p[c]} but listed under parent {p}"

    # 2) No clone appears under multiple parents
    seen = {}
    dupes = []
    for p, clones in parents.items():
        for c in clones:
            if c in seen and seen[c] != p:
                dupes.append((c, seen[c], p))
            else:
                seen[c] = p
    assert not dupes, f"Clone(s) listed under multiple parents: {dupes[:10]}"

    # 3) No parent is listed as its own clone
    bad_self = [p for p, clones in parents.items() if p in clones]
    assert not bad_self, f"Parent(s) listed as their own clone: {bad_self}"

    # 4) Parent names do not appear as clone keys
    parent_names = set(parents.keys())
    bad_parent_as_clone = parent_names.intersection(c2p.keys())
    assert not bad_parent_as_clone, f"Parent(s) also appear as clone keys: {sorted(bad_parent_as_clone)[:10]}"

    # 5) Every child_to_parent pair is represented in parents (since we include only parents with ≥1 clone)
    for c, p in c2p.items():
        assert p in parents, f"child_to_parent refers to parent {p} not present in parents map"
        assert c in parents[p], f"{c} -> {p} missing from parents[{p}] list"

def test_clone_lists_are_sorted_and_unique(outputs_dir):
    DOC = (outputs_dir / "mame_parent_index.json")
    d = json.loads(DOC.read_text(encoding="utf-8"))
    parents = d["parents"]
    for p, clones in parents.items():
        assert clones == sorted(clones), f"{p}: clones not sorted"
        assert len(clones) == len(set(clones)), f"{p}: duplicates in clone list"
