import ast
from collections.abc import Iterator
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def iter_cycle_guard_paths() -> Iterator[Path]:
    yield from sorted((SRC_ROOT / "cast" / "models").rglob("*.py"))
    yield SRC_ROOT / "cast" / "wagtail_panels.py"
    yield from sorted((SRC_ROOT / "cast" / "transcripts").rglob("*.py"))


def file_package(path: Path) -> str:
    relative_parts = path.relative_to(SRC_ROOT).with_suffix("").parts
    if relative_parts[-1] == "__init__":
        return ".".join(relative_parts[:-1])
    return ".".join(relative_parts[:-1])


def resolve_import_from(path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    package_parts = file_package(path).split(".")
    if node.level > 1:
        package_parts = package_parts[: -(node.level - 1)]
    if node.module:
        package_parts.extend(node.module.split("."))
    return ".".join(package_parts)


def iter_resolved_imports(path: Path) -> Iterator[tuple[int, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.lineno, resolve_import_from(path, node)


def test_models_initialisation_imports_do_not_depend_on_voxhelm_package():
    violations = []
    for path in iter_cycle_guard_paths():
        for lineno, resolved_name in iter_resolved_imports(path):
            if resolved_name == "cast.voxhelm" or resolved_name.startswith("cast.voxhelm."):
                violations.append(f"{path.relative_to(SRC_ROOT)}:{lineno}: {resolved_name}")

    assert not violations, "cast.models initialisation imports must not depend on cast.voxhelm:\n" + "\n".join(
        violations
    )
