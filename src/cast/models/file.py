"""Historical migration support for the removed generic ``File`` model.

The ``File`` model and its admin were removed (migration 0090 drops the table).
Migration 0089 still references ``cast.models.file.validate_file_extension`` by
import path, so this module keeps that name importable. It is never attached to a
live field and accepts every value.
"""

from typing import Any


def validate_file_extension(value: Any) -> None:
    """No-op kept so historical migration 0089 can still be imported."""
