import ast
from pathlib import Path

CONTENT_ROOT = Path(__file__).resolve().parents[2] / "src" / "cast" / "content"


def test_content_package_does_not_import_drf():
    assert CONTENT_ROOT.is_dir()
    violations = []
    paths = sorted(CONTENT_ROOT.rglob("*.py"))
    assert paths
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "rest_framework" or name.startswith("rest_framework.") for name in names):
                violations.append(f"{path.relative_to(CONTENT_ROOT)}:{node.lineno}")

    assert not violations, "cast.content must not import Django REST framework:\n" + "\n".join(violations)
