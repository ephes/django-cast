import ast
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"


def test_blog_index_service_imports_before_django_setup():
    result = subprocess.run(
        [sys.executable, "-c", "import cast.blog_index"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


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


def resolved_import_from_names(path: Path, node: ast.ImportFrom) -> Iterator[str]:
    module_name = resolve_import_from(path, node)
    for alias in node.names:
        if alias.name == "*":
            yield module_name
        elif module_name:
            yield f"{module_name}.{alias.name}"
        else:
            yield alias.name


def iter_resolved_imports(path: Path) -> Iterator[tuple[int, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield from ((node.lineno, name) for name in resolved_import_from_names(path, node))


def test_import_from_names_include_absolute_and_relative_aliases():
    path = SRC_ROOT / "cast" / "models" / "example.py"
    source = "from cast import blocks\nfrom cast.blocks import GalleryBlock\nfrom .. import filters\n"
    nodes = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]

    resolved_names = [name for node in nodes for name in resolved_import_from_names(path, node)]

    assert resolved_names == ["cast.blocks", "cast.blocks.GalleryBlock", "cast.filters"]


def test_models_initialisation_imports_do_not_depend_on_voxhelm_package():
    violations = []
    for path in iter_cycle_guard_paths():
        for lineno, resolved_name in iter_resolved_imports(path):
            if resolved_name == "cast.voxhelm" or resolved_name.startswith("cast.voxhelm."):
                violations.append(f"{path.relative_to(SRC_ROOT)}:{lineno}: {resolved_name}")

    assert not violations, "cast.models initialisation imports must not depend on cast.voxhelm:\n" + "\n".join(
        violations
    )


def test_models_do_not_import_presentation_block_or_filter_modules():
    forbidden_modules = {"cast.blocks", "cast.filters"}
    violations = []
    for path in sorted((SRC_ROOT / "cast" / "models").rglob("*.py")):
        for lineno, resolved_name in iter_resolved_imports(path):
            if any(
                resolved_name == forbidden or resolved_name.startswith(f"{forbidden}.")
                for forbidden in forbidden_modules
            ):
                violations.append(f"{path.relative_to(SRC_ROOT)}:{lineno}: {resolved_name}")

    assert not violations, "cast.models must use neutral schema/query modules:\n" + "\n".join(violations)
