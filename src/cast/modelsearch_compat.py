"""Compatibility patch for the ``modelsearch`` SQLite full-text search backend on Django 6.1.

Django 6.1 restructured ``DatabaseOperations.conditional_expression_supported_in_where_clause``:
on backends without a native boolean field - SQLite - only ``Exists``, ``Lookup`` and ``WhereNode``
conditions still compile bare, every other boolean-output expression is wrapped in ``= True``.
``modelsearch`` (<= 1.3.1, the search backend Wagtail delegates to) filters the FTS index with a
plain ``Expression`` subclass, so the generated SQL becomes ``<fts_table> MATCH ? = ?``, which
SQLite rejects with ``unable to use function MATCH in the requested context``.

Wrapping the match expression in a ``Lookup`` subclass keeps it on Django's condition whitelist
while emitting exactly the same SQL. Remove this module and its call in
``cast.apps.CastConfig.ready()`` once ``modelsearch`` ships a fix.
"""

from __future__ import annotations

from typing import Any

from django import VERSION as DJANGO_VERSION
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Lookup, Value

# First Django version that refuses bare non-``Lookup`` conditions on SQLite.
FIRST_AFFECTED_DJANGO_VERSION = (6, 1)


class MatchCondition(Lookup):
    """Present a modelsearch ``MatchExpression`` to Django as a filter condition."""

    def __init__(self, match_expression: Any) -> None:
        self.match_expression = match_expression
        self.lhs = match_expression
        self.rhs = Value(True)

    def resolve_expression(self, *args: Any, **kwargs: Any) -> MatchCondition:
        # The wrapped expression is built ready to compile, there is nothing to resolve.
        return self

    def as_sql(self, compiler: Any, connection: Any) -> Any:
        return self.match_expression.as_sql(compiler, connection)


def build_match_condition(columns: list[str], query: Any) -> MatchCondition:
    """Drop-in replacement for ``MatchExpression`` at modelsearch's single SQLite call site."""
    from modelsearch.backends.database.sqlite.query import MatchExpression

    return MatchCondition(MatchExpression(columns, query))


def apply_modelsearch_sqlite_match_patch(django_version: tuple[Any, ...] = DJANGO_VERSION) -> bool:
    """Make modelsearch build its SQLite FTS filter as a ``Lookup``. Return whether it was applied."""
    if django_version < FIRST_AFFECTED_DJANGO_VERSION:
        return False
    try:
        from modelsearch.backends.database.sqlite import sqlite as modelsearch_sqlite
    except (ImportError, ImproperlyConfigured, LookupError):  # pragma: no cover - sqlite backend unavailable
        # Importing the backend needs the ``modelsearch`` app itself: Wagtail only delegates
        # search to it from 7.1 on, and it may be missing from ``INSTALLED_APPS`` entirely.
        # On non-SQLite databases (e.g. PostgreSQL) the ``SQLiteFTSIndexEntry`` model is never
        # defined, so the import raises ``LookupError`` - the patch is not needed there either.
        return False
    if modelsearch_sqlite.MatchExpression is build_match_condition:
        return False
    modelsearch_sqlite.MatchExpression = build_match_condition
    return True
