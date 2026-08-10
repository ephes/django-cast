from django.core.exceptions import ImproperlyConfigured
import pytest

from cast.modelsearch_compat import MatchCondition, apply_modelsearch_sqlite_match_patch, build_match_condition

try:
    from modelsearch.backends.database.sqlite import sqlite as modelsearch_sqlite
    from modelsearch.backends.database.sqlite.query import MatchExpression
except (ImportError, ImproperlyConfigured):
    modelsearch_sqlite = MatchExpression = None  # type: ignore[assignment]

requires_modelsearch = pytest.mark.skipif(
    modelsearch_sqlite is None, reason="Wagtail registers the modelsearch app only from 7.1 on"
)


class StubMatchExpression:
    def as_sql(self, compiler, connection):
        return "fts_table MATCH %s", ["{title} : (foo)"]


def test_match_condition_delegates_to_the_wrapped_expression():
    condition = MatchCondition(StubMatchExpression())

    assert condition.resolve_expression() is condition
    assert condition.as_sql(compiler=None, connection=None) == ("fts_table MATCH %s", ["{title} : (foo)"])


def test_patch_is_not_applied_before_django_61():
    assert apply_modelsearch_sqlite_match_patch(django_version=(6, 0, 0, "final", 0)) is False


@requires_modelsearch
def test_build_match_condition_wraps_a_real_match_expression():
    condition = build_match_condition(["title"], "foo")

    assert isinstance(condition, MatchCondition)
    assert isinstance(condition.match_expression, MatchExpression)
    assert condition.match_expression.columns == ["title"]


@requires_modelsearch
def test_patch_rebinds_the_match_expression_call_site_once(monkeypatch):
    monkeypatch.setattr(modelsearch_sqlite, "MatchExpression", MatchExpression)

    assert apply_modelsearch_sqlite_match_patch(django_version=(6, 1, 0, "final", 0)) is True
    assert modelsearch_sqlite.MatchExpression is build_match_condition
    assert apply_modelsearch_sqlite_match_patch(django_version=(6, 1, 0, "final", 0)) is False
