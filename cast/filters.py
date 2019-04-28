from datetime import datetime

import django_filters

from watson import search as watson

from .models import Post
from .widgets import DateFacetWidget


def parse_date_facets(value):
    """Split into function, because it needs to be imported by the post list view."""
    year_month = datetime.strptime(value, "%Y-%m")
    return year_month


class FacetChoicesMixin:
    """Just a way to pass the facet counts to the field which displays the choice."""

    @property
    def field(self):
        facet_count_choices = []
        for year_month, count in sorted(
            self.parent.facet_counts.get("year_month", {}).items()
        ):
            date_str = year_month.strftime("%Y-%m")
            label = f"{date_str} ({count})"
            facet_count_choices.append((date_str, label))
        self.extra["choices"] = facet_count_choices
        return super().field


class DateFacetFilter(FacetChoicesMixin, django_filters.filters.ChoiceFilter):
    def filter(self, qs, value):
        if len(value) == 0:
            # don't filter if value is empty
            return qs
        year_month = parse_date_facets(value)
        year = year_month.year
        month = year_month.month
        return qs.filter(visible_date__year=year, visible_date__month=month)


class PostFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        field_name="title", method="fulltext_search", label="Search"
    )
    date = django_filters.DateFromToRangeFilter(
        field_name="visible_date",
        label="Date",
        widget=django_filters.widgets.DateRangeWidget(
            attrs={"type": "date", "placeholder": "YYYY/MM/DD"}
        ),
    )
    date_facets = DateFacetFilter(
        field_name="title",
        label="Date Facets",
        choices=[],
        widget=DateFacetWidget(attrs={"class": "cast-date-facet-container"}),
    )
    o = django_filters.OrderingFilter(
        fields=(("visible_date", "visible_date"),),
        field_labels={"visible_date": "Date"},
    )

    class Meta:
        model = Post
        fields = ["search", "date", "date_facets"]

    def __init__(
        self,
        data=None,
        queryset=None,
        *,
        request=None,
        prefix=None,
        blog=None,
        facet_counts=None,
    ):
        super().__init__(data=data, queryset=queryset, request=request, prefix=prefix)
        self.blog = blog
        self.facet_counts = facet_counts

    def fulltext_search(self, queryset, name, value):
        return watson.filter(queryset, value)
