"""Check installer-facing security constraints at supported release boundaries."""

import configparser
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


@pytest.mark.parametrize(
    ("package", "version", "allowed"),
    [
        ("django", "5.2.16", False),
        ("django", "5.2.17", True),
        ("django", "6.0.0", False),
        ("django", "6.0.7", False),
        ("django", "6.0.8", True),
        ("django", "6.1.0", False),  # CVE-2026-15830 in the advisory-floor audit.
        ("django", "6.1.1", True),
        ("django", "6.1.2", True),
        ("django", "7.0", False),
        ("djangorestframework", "3.17.2", False),  # CVE-2026-114136/114137/114138.
        ("djangorestframework", "3.18.1", False),
        ("djangorestframework", "3.18.2", True),
        ("djangorestframework", "3.18.3", True),
        ("pillow", "12.3.0", False),  # 39 advisories in the floor audit, fixed in 13.0.0.
        ("pillow", "13.0.0", True),
        ("pillow", "13.1.0", True),
        ("soupsieve", "2.9.0", False),
        ("soupsieve", "4.0.0", False),
        ("soupsieve", "4.0.1", False),
        ("soupsieve", "4.1", True),  # Security floor including CVE-2026-126190 fixes.
        ("soupsieve", "4.1.1", True),
        ("urllib3", "2.7.0", False),
        ("urllib3", "2.8.0", True),
        ("urllib3", "2.9.0", True),
    ],
)
def test_security_release_boundaries(package, version, allowed):
    """Reject vulnerable pins without dropping the supported patched branches."""
    metadata = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    dependency = next(
        requirement
        for dependency in metadata["project"]["dependencies"]
        if (requirement := Requirement(dependency)).name.lower() == package
    )
    assert dependency.specifier.contains(version) is allowed


def test_vitest_security_floor_and_peer_alignment():
    import json

    from packaging.version import Version

    lock = json.loads((Path(__file__).resolve().parents[1] / "javascript/package-lock.json").read_text())
    packages = lock["packages"]
    version = packages["node_modules/vitest"]["version"]
    assert Version(version) >= Version("4.1.12")
    for name, package in packages.items():
        if name.startswith("node_modules/@vitest/"):
            assert package["version"] == version


def test_full_javascript_audit_is_available_manually():
    import shlex

    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/workflow.yml").read_text()
    triggers = workflow.split("jobs:", 1)[0]
    assert "\non: workflow_dispatch\n" in triggers
    assert "\npermissions:\n  contents: read\n" in triggers
    job = workflow.split("  javascript-audit:\n", 1)[1].split("\n  javascript:\n", 1)[0]
    job_lines = job.splitlines()
    assert not any(line.startswith(("    if:", "    needs:")) for line in job_lines)
    audit = next(line.strip().removeprefix("run: ") for line in job.splitlines() if "run: npm audit" in line)
    args = shlex.split(audit)
    assert "working-directory: javascript" in job
    assert "--package-lock-only" in args and "--include=dev" in args
    assert not any(arg.startswith(("--omit", "--audit-level", "--production")) for arg in args)


def test_test_dependencies_have_one_source():
    root = Path(__file__).resolve().parents[1]
    groups = tomllib.loads((root / "pyproject.toml").read_text())["dependency-groups"]
    test_packages = {canonicalize_name(Requirement(dependency).name) for dependency in groups["test"]}
    assert {"include-group": "test"} in groups["dev"]
    assert "playwright" not in test_packages
    assert all(
        canonicalize_name(Requirement(dependency).name) not in test_packages
        for dependency in groups["dev"]
        if isinstance(dependency, str)
    )
    tox = configparser.ConfigParser(interpolation=None)
    tox.read(root / "tox.ini")
    assert tox["testenv"]["dependency_groups"].strip() == "test"
    assert not any(
        canonicalize_name(Requirement(dependency).name) in test_packages
        for dependency in tox["testenv"]["deps"].splitlines()
        if dependency and ":" not in dependency
    )
    for environment in ("cleanup", "pre-commit"):
        assert not tox[f"testenv:{environment}"]["dependency_groups"].strip()


def test_soupsieve_audit_checks_the_declared_floor():
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    requirement = next(
        Requirement(dependency)
        for dependency in metadata["project"]["dependencies"]
        if Requirement(dependency).name == "soupsieve"
    )
    floor = next(specifier.version for specifier in requirement.specifier if specifier.operator == ">=")
    floors = (root / "scripts/advisory-floors.txt").read_text().splitlines()
    assert f"soupsieve=={floor}" in floors


def test_all_workflows_are_manual_only():
    root = Path(__file__).resolve().parents[1]
    for path in (root / ".github/workflows").glob("*.y*ml"):
        workflow = path.read_text()
        assert workflow.split("\non:", 1)[1].split("\n", 1)[0] == " workflow_dispatch", path
