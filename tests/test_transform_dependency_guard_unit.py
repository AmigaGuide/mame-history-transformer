import ast
from pathlib import Path


def test_transformer_is_guarded_by_upstream_success():
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    main_func = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "main"
    )

    guarded_calls = []

    for node in ast.walk(main_func):
        if not isinstance(node, ast.If):
            continue

        # Identify the condition checking failed_dependencies.
        if not (
            isinstance(node.test, ast.Name)
            and node.test.id == "failed_dependencies"
        ):
            continue

        # The transform must only run in the else branch.
        for statement in node.orelse:
            for child in ast.walk(statement):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "run_transformer"
                ):
                    guarded_calls.append(child)

    all_transform_calls = [
        node
        for node in ast.walk(main_func)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_transformer"
        )
    ]

    assert len(all_transform_calls) == 1
    assert len(guarded_calls) == 1
