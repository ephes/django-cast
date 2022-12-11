import string
from datetime import datetime
from itertools import chain

import django_filters
from django.db import models
from django.db.models.fields import BLANK_CHOICE_DASH
from django.forms import Widget
from django.forms.utils import flatatt
from django.utils.encoding import force_str
from django.utils.http import urlencode
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _


class DateFacetWidget(Widget):
    def __init__(self, attrs=None, choices=()):
        super().__init__(attrs)

        self.choices = choices

    def value_from_datadict(self, data, files, name):
        value = super().value_from_datadict(data, files, name)
        self.data = data
        return value

    def render(self, name, value, attrs=None, choices=(), renderer=None):
        if not hasattr(self, "data"):
            self.data = {}
        if value is None:
            value = ""
        final_attrs = self.build_attrs(self.attrs, extra_attrs=attrs)
        output = ["<div%s>" % flatatt(final_attrs)]
        options = self.render_options(choices, [value], name)
        if options:
            output.append(options)
        output.append("</div>")
        return mark_safe("\n".join(output))

    def render_options(self, choices, selected_choices, name):
        selected_choices = {force_str(v) for v in selected_choices}
        output = []
        for option_value, option_label in chain(self.choices, choices):
            if isinstance(option_label, (list, tuple)):
                for option in option_label:
                    output.append(self.render_option(name, selected_choices, *option))
            else:
                output.append(self.render_option(name, selected_choices, option_value, option_label))
        return "\n".join(output)

    def render_option(self, name, selected_choices, option_value, option_label):
        option_value = force_str(option_value)
        if option_label == BLANK_CHOICE_DASH[0][1]:
            option_label = _("All")
        data = self.data.copy()
        data[name] = option_value
        selected = data == self.data or option_value in selected_choices
        try:
            url = data.urlencode()
        except AttributeError:
            url = urlencode(data)
        return self.option_string() % {
            "attrs": selected and ' class="selected"' or "",
            "query_string": url,
            "label": force_str(option_label),
        }

    def option_string(self):
        return '<div class="cast-date-facet-item"><a%(attrs)s href="?%(query_string)s">%(label)s</a></div>'


def parse_date_facets(value):
    """Split into function, because it needs to be imported by the post list view."""
    # clean up value a little bit, because otherwise sql-injection
    # search requests are spamming the logfile with garbage -> analytics wont work
    allowed = set(string.digits + "-")
    value = "".join([c for c in value if c in allowed])
    year_month = datetime.strptime(value, "%Y-%m")
    return year_month


def get_selected_facet(get_params):
    date_facet = get_params.get("date_facets")
    if date_facet is None or len(date_facet) == 0:
        return None
    return parse_date_facets(date_facet)


def get_facet_counts(filterset_data, queryset):
    filterset_data = {k: v for k, v in filterset_data.items()}  # copy filterset_data to avoid overwriting

    # get selected facet if set and build the facet counting queryset
    facet_counts = {}
    selected_facet = get_selected_facet(filterset_data)
    if selected_facet is not None:
        facet_counts = {"year_month": {selected_facet: 1}}
    filterset_data["facet_counts"] = facet_counts
    post_filter = PostFilterset(queryset=queryset, data=filterset_data, facet_counts=facet_counts)
    facet_queryset = (
        post_filter.qs.order_by()
        .annotate(month=models.functions.TruncMonth("visible_date"))
        .values("month")
        .annotate(n=models.Count("pk"))
    )

    # build up the date facet counts for final filter pass
    year_month_counts = {}
    for row in facet_queryset:
        year_month_counts[row["month"]] = row["n"]
    return {"year_month": year_month_counts}


class FacetChoicesMixin:
    """Just a way to pass the facet counts to the field which displays the choice."""

    @property
    def field(self):
        facet_count_choices = []
        for year_month, count in sorted(self.parent.facet_counts.get("year_month", {}).items()):
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


class PostFilterset(django_filters.FilterSet):
    search = django_filters.CharFilter(field_name="title", method="fulltext_search", label="Search")
    date = django_filters.DateFromToRangeFilter(
        field_name="visible_date",
        label="Date",
        widget=django_filters.widgets.DateRangeWidget(attrs={"type": "date", "placeholder": "YYYY/MM/DD"}),
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
        fields = ["search", "date", "date_facets"]

    def __init__(
        self,
        data=None,
        queryset=None,
        *,
        facet_counts={},
        fetch_facet_counts=False,
    ):
        super().__init__(data=data, queryset=queryset)
        self.facet_counts = facet_counts
        if fetch_facet_counts:
            # avoid running into infinite recursion problems, because
            # get_facet_counts will instantiate Postfilterset again
            # -> and again -> and again ...
            try:
                self.facet_counts = get_facet_counts(data, queryset)
            except ValueError:
                self.facet_counts = {}

    @staticmethod
    def fulltext_search(queryset, name, value):
        return queryset.search(value).get_queryset()
