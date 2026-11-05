"""Keep module paths in the Sphinx docs in step with the source layout."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
SRC_DIR = REPO_ROOT / "src"
PACKAGE_DIR = SRC_DIR / "cast"
ARCHITECTURE = DOCS_DIR / "architecture.rst"

LITERAL = re.compile(r"``([A-Za-z0-9_./-]+)``")
# Only prefixes that name a location unambiguously: bare file names such as
# ``blocks.py`` or ``settings.py`` may mean a project file, not a cast module.
PREFIXES = {
    "src/cast/": REPO_ROOT,
    "cast/": SRC_DIR,
    "models/": PACKAGE_DIR,
}
TREE_LINE = re.compile(r"^    (?P<indent>(?:│   |    )*)[├└]── (?P<names>[^#]+?)\s*(?:#.*)?$")
IGNORED_TOP_LEVEL = {"__pycache__"}


def package_entries(directory: Path) -> set[str]:
    """Return the module files and subpackages/directories, ignoring local clutter.

    Dotfiles (``.DS_Store``) and editor leftovers are gitignored or untracked,
    so they must not count as undocumented modules.
    """
    return {
        path.name
        for path in directory.iterdir()
        if path.name not in IGNORED_TOP_LEVEL
        and not path.name.startswith(".")
        and (path.is_dir() or path.suffix == ".py")
    }


def documented_module_paths() -> list[tuple[str, str]]:
    found = []
    for rst in sorted(DOCS_DIR.rglob("*.rst")):
        if "_build" in rst.parts:
            continue
        for literal in LITERAL.findall(rst.read_text()):
            if literal.endswith(".py") or literal.endswith("/"):
                if any(literal.startswith(prefix) for prefix in PREFIXES):
                    found.append((str(rst.relative_to(REPO_ROOT)), literal))
    return found


@pytest.mark.parametrize("doc, literal", documented_module_paths())
def test_documented_module_path_exists(doc: str, literal: str) -> None:
    prefix = next(prefix for prefix in PREFIXES if literal.startswith(prefix))
    assert (PREFIXES[prefix] / literal).exists(), f"{doc} mentions missing path {literal}"


def code_organization_tree() -> list[str]:
    text = ARCHITECTURE.read_text()
    section = text.split("Code Organization\n-----------------\n", 1)[1]
    block = section.split(".. code-block:: text\n\n", 1)[1]
    lines = []
    for line in block.splitlines():
        if line and not line.startswith("    "):
            break
        lines.append(line)
    assert lines[0] == "    src/cast/"
    return lines[1:]


def tree_entries() -> list[Path]:
    """Return the paths, relative to ``src/cast``, that the tree lists."""
    entries: list[Path] = []
    parents: list[Path] = []
    for line in code_organization_tree():
        match = TREE_LINE.match(line)
        if match is None:
            continue
        depth = len(match["indent"]) // 4
        del parents[depth:]
        base = parents[-1] if parents else Path()
        for name in match["names"].split(","):
            name = name.strip()
            path = base / name.rstrip("/")
            entries.append(path)
            if name.endswith("/"):
                parents.append(path)
    return entries


def test_code_organization_entries_exist() -> None:
    missing = [str(path) for path in tree_entries() if not (PACKAGE_DIR / path).exists()]
    assert missing == []


def test_code_organization_lists_every_top_level_module() -> None:
    listed = {path.parts[0] for path in tree_entries()}
    actual = package_entries(PACKAGE_DIR)
    assert sorted(actual - listed) == []


def test_code_organization_lists_every_models_module() -> None:
    listed = {path.name for path in tree_entries() if path.parts[0] == "models" and len(path.parts) == 2}
    actual = package_entries(PACKAGE_DIR / "models") - {"__init__.py"}
    assert sorted(actual - listed) == []
