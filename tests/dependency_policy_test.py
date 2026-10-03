"""Check installer-facing security constraints at supported release boundaries."""

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement


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
