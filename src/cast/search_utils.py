from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol, cast

from django.db import models
from modelsearch.backends.base import BaseSearchResults

MODELSEARCH_QUERY_MAX_LENGTH = 500


if TYPE_CHECKING:

    class SearchResultsQuerySet(Protocol):
        def get_queryset(self) -> models.QuerySet: ...

    class ModelSearchQuerySet(Protocol):
        def none(self) -> models.QuerySet: ...

        def search(self, query: str) -> object: ...

else:
    SearchResultsQuerySet = object
    ModelSearchQuerySet = object


def normalize_modelsearch_query(raw_value: str) -> str:
    value = raw_value.replace("\x00", "")
    value = re.sub(r"[\s\-]+", " ", value).strip()
    # Truncation can leave a trailing collapsed space.
    return value[:MODELSEARCH_QUERY_MAX_LENGTH].rstrip()


def safe_fulltext_queryset(queryset: ModelSearchQuerySet, raw_value: str) -> models.QuerySet:
    cleaned = normalize_modelsearch_query(raw_value)
    if not cleaned:
        return queryset.none()
    search_results = cast(SearchResultsQuerySet, queryset.search(cleaned))
    return search_results.get_queryset()


def safe_modelsearch_results(queryset: ModelSearchQuerySet, raw_value: str) -> models.QuerySet | BaseSearchResults:
    cleaned = normalize_modelsearch_query(raw_value)
    if not cleaned:
        return cast(models.QuerySet, queryset)
    return cast(BaseSearchResults, queryset.search(cleaned))
