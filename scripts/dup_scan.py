# Scan for duplicate function names and identical function bodies across files.
import ast
import hashlib
from pathlib import Path

ROOT = Path("src")
FILES = [p for p in ROOT.rglob("*.py") if p.name != "__init__.py"]

# Build a safe tuple of "string literal" node types (Constant exists 3.8+)
STR_NODE = getattr(ast, "Constant", None)
STR_TYPES = (ast.Str,) if STR_NODE is None else (ast.Str, STR_NODE)

def strip_docstring(body):
    """Remove leading docstring expression if present."""
    if not body:
        return body
    first = body[0]
    val = getattr(first, "value", None)
    if isinstance(first, ast.Expr) and isinstance(val, STR_TYPES):
        return body[1:]
    return body

def normalise_func(node: ast.AST) -> str:
    """
    Return a canonical representation of a function suitable for hashing:
    - Drop decorators and docstring
    - Keep signature and returns
    - Zero out line/col metadata
    """
    if isinstance(node, ast.FunctionDef):
        new = ast.FunctionDef(
            name="FN",
            args=node.args,
            body=strip_docstring(list(node.body)),
            decorator_list=[],
            returns=node.returns,
            type_comment=None,
        )
    elif hasattr(ast, "AsyncFunctionDef") and isinstance(node, ast.AsyncFunctionDef):
        new = ast.AsyncFunctionDef(
            name="FN",
            args=node.args,
            body=strip_docstring(list(node.body)),
            decorator_list=[],
            returns=node.returns,
            type_comment=None,
        )
    else:
        raise TypeError("Expected FunctionDef/AsyncFunctionDef")

    # Normalise location info for stable dumps
    ast.fix_missing_locations(new)
    for n in ast.walk(new):
        for attr in ("lineno", "col_offset", "end_lineno", "end_col_offset"):
            if hasattr(n, attr):
                setattr(n, attr, None)

    # Prefer unparse if available (3.9+); otherwise use a stable dump
    if hasattr(ast, "unparse"):
        try:
            return ast.unparse(new)
        except Exception:
            pass
    return ast.dump(new, include_attributes=False)

def hash_func(node: ast.AST) -> str:
    return hashlib.sha256(normalise_func(node).encode("utf-8")).hexdigest()

index_by_name = {}  # name -> [(path, lineno)]
index_by_hash = {}  # hash -> [(name, path, lineno)]

for f in FILES:
    try:
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        continue
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, getattr(ast, "AsyncFunctionDef", tuple()))):
            index_by_name.setdefault(n.name, []).append((f, n.lineno))
            h = hash_func(n)
            index_by_hash.setdefault(h, []).append((n.name, f, n.lineno))

print("# Same function names in multiple files")
for name in sorted(index_by_name):
    locs = index_by_name[name]
    if len(locs) > 1:
        print(f"{name} ({len(locs)})")
        for f, ln in sorted(locs, key=lambda x: (str(x[0]), x[1])):
            print(f"  - {f}:{ln}")

print("\n# Identical function bodies across files (hash match)")
for h, entries in index_by_hash.items():
    files_set = {str(p) for _, p, _ in entries}
    if len(files_set) > 1:
        names = ", ".join(sorted({n for n, _, _ in entries}))
        print(f"[{h[:10]}] {names}")
        for n, f, ln in sorted(entries, key=lambda x: (str(x[1]), x[2])):
            print(f"  - {f}:{ln} :: {n}")
