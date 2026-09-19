"""Opt-in pytest guard for the PostgreSQL-only CI environment."""

import pytest
from django.db import connection


def pytest_sessionstart(session: pytest.Session) -> None:
    if connection.vendor != "postgresql":
        raise pytest.UsageError(
            "The postgres tox environment requires a PostgreSQL backend; refusing skipped lock tests."
        )
