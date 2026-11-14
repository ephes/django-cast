"""Shared integer admission for transcript maintenance commands."""

from typing import Any

from django.core.management.base import CommandError
from django.db import connections, models, router


def positive_id(value: Any, model: type[models.Model]) -> int:
    using = router.db_for_read(model)
    field = model._meta.pk
    while isinstance(field, models.ForeignKey):
        field = field.target_field
    lower, upper = connections[using].ops.integer_field_range(field.get_internal_type())
    text = str(value)
    if (
        type(value) not in (int, str)
        or not text.isascii()
        or not text.isdecimal()
        or text.startswith("0")
        or len(text) > len(str(upper))
    ):
        raise CommandError("Expected a canonical positive integer ID within the database field range.")
    number = int(text)
    if not max(1, lower) <= number <= upper:
        raise CommandError("Expected a canonical positive integer ID within the database field range.")
    return number


def is_id_selector(value: str) -> bool:
    return value.isnumeric() or value.lstrip("+-").isnumeric()
