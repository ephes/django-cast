import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

from django.core import validators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Expression
from django.db.models.functions import TruncMonth
from taggit.models import Tag

from cast import appsettings
from cast.filters import PostFilterset, parse_date_facets
from cast.models import Blog
from cast.models.snippets import PostCategory

logger = logging.getLogger(__name__)

ModalFacetName = Literal["date_facets", "tag_facets", "category_facets"]
MODAL_FACET_NAMES: tuple[ModalFacetName, ...] = ("date_facets", "tag_facets", "category_facets")


class ModalFacetOption(TypedDict):
    slug: str
    name: str
    count: int


class ModalFacetGroup(TypedDict):
    selected: str
    all_count: int
    options: list[ModalFacetOption]


class ModalFacetResponse(TypedDict):
    mode: Literal["modal"]
    result_count: int
    groups: dict[ModalFacetName, ModalFacetGroup]


@dataclass(frozen=True)
class ModalFacetSelection:
    search: str
    date_facets: str
    tag_facets: str
    category_facets: str
    o: str

    def get(self, name: ModalFacetName) -> str:
        return getattr(self, name)


@dataclass
class AggregationQueryResolver:
    supports_aggregation: bool | None = None

    def get_queryset_for_aggregation(self, queryset: models.QuerySet) -> models.QuerySet:
        if self.supports_aggregation is None:
            self.supports_aggregation = _supports_aggregation_on_queryset(queryset)
        if self.supports_aggregation:
            return queryset
        return _queryset_from_pk_fallback(queryset)


def get_modal_facet_counts(blog: Blog, params: Mapping[str, str]) -> ModalFacetResponse:
    selection = _normalize_selection(params)
    configured_groups = _get_configured_modal_groups()
    base_queryset = blog.unfiltered_published_posts
    aggregation_resolver = AggregationQueryResolver()

    result_queryset = _apply_selection(base_queryset, selection)
    result_count = _count_posts(result_queryset, aggregation_resolver)

    groups: dict[ModalFacetName, ModalFacetGroup] = {}
    for group_name in configured_groups:
        selection_without_group = _apply_selection(base_queryset, selection, excluded_group=group_name)
        all_count = _count_posts(selection_without_group, aggregation_resolver)
        filtered_counts = _fetch_group_counts(group_name, selection_without_group, aggregation_resolver)
        universe = _fetch_universe(group_name, base_queryset, aggregation_resolver)
        options: list[ModalFacetOption] = []
        for slug, name in universe:
            options.append({"slug": slug, "name": name, "count": filtered_counts.get(slug, 0)})
        groups[group_name] = {
            "selected": selection.get(group_name),
            "all_count": all_count,
            "options": options,
        }

    return {"mode": "modal", "result_count": result_count, "groups": groups}


def _get_configured_modal_groups() -> list[ModalFacetName]:
    configured = set(appsettings.CAST_FILTERSET_FACETS)
    return [group_name for group_name in MODAL_FACET_NAMES if group_name in configured]


def _normalize_selection(params: Mapping[str, str]) -> ModalFacetSelection:
    search = _get_param(params, "search")
    date_facets = _normalize_date_facet(_get_param(params, "date_facets"))
    tag_facets = _normalize_slug_facet(_get_param(params, "tag_facets"))
    category_facets = _normalize_slug_facet(_get_param(params, "category_facets"))
    ordering = _get_param(params, "o")
    return ModalFacetSelection(
        search=search,
        date_facets=date_facets,
        tag_facets=tag_facets,
        category_facets=category_facets,
        o=ordering,
    )


def _get_param(params: Mapping[str, str], name: str) -> str:
    value = params.get(name)
    if value is None:
        return ""
    return str(value)


def _normalize_date_facet(value: str) -> str:
    if not value:
        return ""
    try:
        year_month = parse_date_facets(value)
    except ValueError:
        return ""
    return year_month.strftime("%Y-%m")


def _normalize_slug_facet(value: str) -> str:
    if not value:
        return ""
    try:
        validators.validate_slug(value)
    except ValidationError:
        return ""
    return value


def _apply_selection(
    queryset: models.QuerySet,
    selection: ModalFacetSelection,
    excluded_group: ModalFacetName | None = None,
) -> models.QuerySet:
    selected_queryset = queryset
    if selection.search:
        selected_queryset = PostFilterset.fulltext_search(selected_queryset, "search", selection.search)

    if excluded_group != "date_facets" and selection.date_facets:
        year_month = parse_date_facets(selection.date_facets)
        selected_queryset = selected_queryset.filter(
            visible_date__year=year_month.year,
            visible_date__month=year_month.month,
        )

    if excluded_group != "tag_facets" and selection.tag_facets:
        selected_queryset = selected_queryset.filter(tags__slug__in=[selection.tag_facets])

    if excluded_group != "category_facets" and selection.category_facets:
        selected_queryset = selected_queryset.filter(categories__slug__in=[selection.category_facets])

    return selected_queryset


def _count_posts(queryset: models.QuerySet, resolver: AggregationQueryResolver) -> int:
    aggregation_queryset = _queryset_for_aggregation(queryset, resolver)
    return aggregation_queryset.order_by().values("pk").distinct().count()


def _fetch_group_counts(
    group_name: ModalFacetName, queryset: models.QuerySet, resolver: AggregationQueryResolver
) -> dict[str, int]:
    if group_name == "date_facets":
        return _fetch_date_counts(queryset, resolver)
    if group_name == "tag_facets":
        return _fetch_tag_counts(queryset, resolver)
    return _fetch_category_counts(queryset, resolver)


def _fetch_universe(
    group_name: ModalFacetName, base_queryset: models.QuerySet, resolver: AggregationQueryResolver
) -> list[tuple[str, str]]:
    if group_name == "date_facets":
        return _fetch_date_universe(base_queryset, resolver)
    if group_name == "tag_facets":
        return _fetch_tag_universe(base_queryset, resolver)
    return _fetch_category_universe(base_queryset, resolver)


def _fetch_date_counts(queryset: models.QuerySet, resolver: AggregationQueryResolver) -> dict[str, int]:
    aggregation_queryset = _queryset_for_aggregation(queryset, resolver)
    rows = (
        aggregation_queryset.order_by()
        .annotate(month=TruncMonth(cast(Expression, models.F("visible_date"))))
        .values("month")
        .annotate(num_posts=models.Count("pk", distinct=True))
        .values_list("month", "num_posts")
    )
    counts: dict[str, int] = {}
    for month, count in rows:
        if month is None:
            continue
        counts[month.strftime("%Y-%m")] = int(count)
    return counts


def _fetch_date_universe(base_queryset: models.QuerySet, resolver: AggregationQueryResolver) -> list[tuple[str, str]]:
    counts = _fetch_date_counts(base_queryset, resolver)
    return [(slug, slug) for slug in sorted(counts.keys(), reverse=True)]


def _fetch_tag_counts(queryset: models.QuerySet, resolver: AggregationQueryResolver) -> dict[str, int]:
    aggregation_queryset = _queryset_for_aggregation(queryset, resolver)
    rows = (
        Tag.objects.annotate(
            num_posts=models.Count("post", filter=models.Q(post__in=aggregation_queryset), distinct=True)
        )
        .filter(num_posts__gt=0)
        .values_list("slug", "num_posts")
    )
    return {slug: int(count) for slug, count in rows}


def _fetch_tag_universe(base_queryset: models.QuerySet, resolver: AggregationQueryResolver) -> list[tuple[str, str]]:
    aggregation_queryset = _queryset_for_aggregation(base_queryset, resolver)
    rows = (
        Tag.objects.annotate(
            num_posts=models.Count("post", filter=models.Q(post__in=aggregation_queryset), distinct=True)
        )
        .filter(num_posts__gt=0)
        .values_list("slug", "name")
    )
    return sorted([(slug, name) for slug, name in rows], key=lambda item: item[0])


def _fetch_category_counts(queryset: models.QuerySet, resolver: AggregationQueryResolver) -> dict[str, int]:
    aggregation_queryset = _queryset_for_aggregation(queryset, resolver)
    rows = (
        PostCategory.objects.annotate(
            num_posts=models.Count("post", filter=models.Q(post__in=aggregation_queryset), distinct=True)
        )
        .filter(num_posts__gt=0)
        .values_list("slug", "num_posts")
    )
    return {slug: int(count) for slug, count in rows}


def _fetch_category_universe(
    base_queryset: models.QuerySet, resolver: AggregationQueryResolver
) -> list[tuple[str, str]]:
    aggregation_queryset = _queryset_for_aggregation(base_queryset, resolver)
    rows = (
        PostCategory.objects.annotate(
            num_posts=models.Count("post", filter=models.Q(post__in=aggregation_queryset), distinct=True)
        )
        .filter(num_posts__gt=0)
        .values_list("slug", "name")
    )
    return sorted([(slug, name) for slug, name in rows], key=lambda item: item[0])


def _queryset_for_aggregation(queryset: models.QuerySet, resolver: AggregationQueryResolver) -> models.QuerySet:
    return resolver.get_queryset_for_aggregation(queryset)


def _supports_aggregation_on_queryset(queryset: models.QuerySet) -> bool:
    try:
        list(queryset.order_by().values("pk").annotate(num_posts=models.Count("pk"))[:1])
    except Exception:
        logger.debug("Modal facet aggregation probe failed; using PK fallback.", exc_info=True)
        return False
    return True


def _queryset_from_pk_fallback(queryset: models.QuerySet) -> models.QuerySet:
    matching_pks = list(queryset.values_list("pk", flat=True))
    if not matching_pks:
        return queryset.model.objects.none()
    return queryset.model.objects.filter(pk__in=matching_pks)
