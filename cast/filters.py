import string
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, cast

import django_filters
from django.core import validators
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models
from django.db.models import Expression
from django.db.models.fields import BLANK_CHOICE_DASH
from django.db.models.functions import TruncMonth
from django.forms import Widget
from django.forms.renderers import BaseRenderer
from django.forms.utils import flatatt
from django.http import QueryDict
from django.utils.datastructures import MultiValueDict
from django.utils.encoding import force_str
from django.utils.safestring import SafeText, mark_safe
from django.utils.translation import gettext as _
from django_filters.fields import ChoiceField as FilterChoiceField
from taggit.models import Tag
from wagtail.models import PageQuerySet

from cast import appsettings
from cast.models.snippets import PostCategory


class CountFacetWidget(Widget):
    data: QueryDict

    def __init__(self, attrs: dict[str, str] | None = None):
        super().__init__(attrs)
        self.choices: list[tuple[str, str]] = []

    def value_from_datadict(  # type: ignore[override]
        self, data: Mapping[str, Iterable[Any]], files: MultiValueDict[str, UploadedFile], name: str
    ) -> str:
        data_for_super = cast(dict[str, Any], data)  # make mypy happy
        value = super().value_from_datadict(data_for_super, files, name)
        self.data: QueryDict = cast(QueryDict, data)
        return value

    def render(
        self, name: str, value: Any, attrs: dict[str, Any] | None = None, renderer: BaseRenderer | None = None
    ) -> SafeText:
        if value is None:
            value = ""
        final_attrs = self.build_attrs(self.attrs, extra_attrs=attrs)
        output = ["<div%s>" % flatatt(final_attrs)]
        options = self.render_options([value], name)
        if options:
            output.append(options)
        output.append("</div>")
        return mark_safe("\n".join(output))

    def render_options(self, selected_choices: list[str], name: str) -> str:
        selected_choices_set = {force_str(v) for v in selected_choices}
        output = []
        for option_value, option_label in self.choices:
            if isinstance(option_label, (list, tuple)):
                for option in option_label:
                    output.append(self.render_option(name, selected_choices_set, option_value, option))
            else:
                output.append(self.render_option(name, selected_choices_set, option_value, option_label))
        return "\n".join(output)

    def render_option(self, name: str, selected_choices: set[str], option_value: str, option_label: str) -> str:
        option_value = force_str(option_value)
        if option_label == BLANK_CHOICE_DASH[0][1]:
            option_label = _("All")

        # remove page from querystring, because otherwise the pagination breaks
        # filters like date facets, str to make mypy happy
        data_dict = {k: str(v) for k, v in self.data.items() if k != "page"}
        data = QueryDict("", mutable=True)
        data.update(data_dict)
        data[name] = option_value

        # build the option string
        url = data.urlencode()
        option_attrs, hidden_input = "", ""
        if option_value in selected_choices:
            # the current option is already selected, so add a hidden input field
            # to preserve the selection and add the class "selected" to the link
            option_attrs = ' class="selected"'
            hidden_input = f'<input type="hidden" name="{name}" value="{option_value}">'
        option_string = self.option_string() % {
            "attrs": option_attrs,
            "query_string": url,
            "label": force_str(option_label),
            "hidden_input": hidden_input,
        }
        return option_string

    @staticmethod
    def option_string() -> str:
        return (
            '<div class="cast-date-facet-item"><a%(attrs)s href="?%(query_string)s">%(label)s</a>'
            "%(hidden_input)s</div>"
        )


def parse_date_facets(value: str) -> datetime:
    """Split into function, because it needs to be imported by the post list view."""
    # clean up value a bit, because otherwise sql-injection
    # search requests are spamming the logfile with garbage -> analytics won't work
    allowed = set(string.digits + "-")
    value = "".join([c for c in value if c in allowed])
    year_month = datetime.strptime(value, "%Y-%m")
    return year_month


DateFacetCounts = dict[datetime, int]
Choices = list[tuple[str, str]]


class DateFacetChoicesMixin:
    """Just a way to pass the facet counts to the field which displays the choice."""

    facet_counts: DateFacetCounts = {}
    extra: dict[str, Any] = {}

    @staticmethod
    def transform_facet_counts_to_choices(facet_counts: DateFacetCounts) -> Choices:
        """
        Transform the facet counts into a list of choices for the field.
        """
        facet_count_choices = []
        for year_month, count in sorted(facet_counts.items()):
            date_str = year_month.strftime("%Y-%m")
            label = f"{date_str} ({count})"
            facet_count_choices.append((date_str, label))
        return facet_count_choices

    def set_field_choices(self, choices: Choices) -> None:
        """
        Set the choices on the field. Also remove the cached _field
        attribute so that the field is recreated with the new choices
        next time it is accessed.

        See django_filters/filters.py:Filter::field for more info.
        """
        self.extra["choices"] = choices
        delattr(self, "_field")


class AllDateChoicesField(FilterChoiceField):
    def valid_value(self, value: str) -> bool:
        """
        Allow all values instead of explicit choices but still validate
        against parse_date_facets to make sure the facet is parseable
        into a date.
        """
        try:
            parse_date_facets(value)
            return True
        except ValueError:
            return False


class DateFacetFilter(DateFacetChoicesMixin, django_filters.filters.ChoiceFilter):
    field_class = AllDateChoicesField

    def filter(self, qs: models.QuerySet, value: str) -> models.QuerySet:
        if len(value) == 0:
            # don't filter if value is empty
            return qs
        year_month = parse_date_facets(value)
        year = year_month.year
        month = year_month.month
        filtered = qs.filter(visible_date__year=year, visible_date__month=month)
        return filtered

    def set_facet_counts(self, queryset: models.QuerySet) -> None:
        """
        Fetch facet counts for filtered queryset and set the field
        choices to the facet counts.
        """
        self.facet_counts = {
            month: num_posts
            for month, num_posts in (
                queryset.order_by()
                .annotate(month=TruncMonth(cast(Expression, models.F("visible_date"))))
                .values("month")
                .annotate(num_posts=models.Count("pk"))
            ).values_list("month", "num_posts")
        }
        choices = self.transform_facet_counts_to_choices(self.facet_counts)
        self.set_field_choices(choices)


class SlugChoicesField(FilterChoiceField):
    def valid_value(self, value: str) -> bool:
        """
        Used to determine if the value provided by the user can be used
        to filter the queryset. Return early if value is not a string,
        use the slug validator to check if the value is a valid slug.
        """
        if not isinstance(value, str):
            return False
        try:
            validators.validate_slug(value)
            return True
        except ValidationError:
            return False


FacetCounts = dict[str, tuple[str, int]]


class CountChoicesMixin:
    """Just a way to pass the facet counts to the field which displays the choice."""

    facet_counts: FacetCounts = {}
    has_facets_with_posts: bool = False
    extra: dict[str, Any] = {}

    @staticmethod
    def fetch_facet_counts(post_queryset: models.QuerySet, count_queryset: models.QuerySet) -> FacetCounts:
        """
        Fetch the facet counts for all facets with post count > 0.
        """
        return {
            slug: (name, num_posts)
            for slug, name, num_posts in count_queryset.annotate(
                num_posts=models.Count("post", filter=models.Q(post__in=post_queryset))
            )
            .filter(num_posts__gt=0)
            .values_list("slug", "name", "num_posts")
        }

    @staticmethod
    def transform_facet_counts_to_choices(facet_counts: FacetCounts) -> Choices:
        """
        Transform the facet counts into a list of choices for the field.
        """
        facet_count_choices = []
        for slug, (name, count) in sorted(facet_counts.items()):
            label = f"{name} ({count})"
            facet_count_choices.append((slug, label))
        return facet_count_choices

    def set_field_choices(self, choices: Choices) -> None:
        """
        Set the choices on the field. Also remove the cached _field
        attribute so that the field is recreated with the new choices
        next time it is accessed.

        Also set the has_facets_with_posts attribute to True if there
        are any facets with posts. This is used to determine if the
        form field should be hidden.
        """
        self.extra["choices"] = choices
        delattr(self, "_field")
        self.has_facets_with_posts = len(choices) > 0

    @property
    def hide_form_field(self) -> bool:
        """True if there are no facets containing posts."""
        return not self.has_facets_with_posts


class CategoryFacetFilter(CountChoicesMixin, django_filters.filters.ChoiceFilter):
    field_class = SlugChoicesField

    def filter(self, qs: models.QuerySet, value: str):
        # Check if value is provided (not None and not an empty list)
        if value:
            return qs.filter(categories__slug__in=[value])
        return qs

    def set_facet_counts(self, queryset: models.QuerySet) -> None:
        """
        Fetch the facet counts for all facets with post count > 0
        and set the choices on the field.
        """
        self.facet_counts = self.fetch_facet_counts(queryset, PostCategory.objects.all())
        choices = self.transform_facet_counts_to_choices(self.facet_counts)
        self.set_field_choices(choices)


class TagFacetFilter(CountChoicesMixin, django_filters.filters.ChoiceFilter):
    field_class = SlugChoicesField
    facet_count_key = "tags"

    def filter(self, qs: models.QuerySet, value: str):
        # Check if value is provided (not None and not an empty list)
        if value:
            return qs.filter(tags__slug__in=[value])
        return qs

    def set_facet_counts(self, queryset: models.QuerySet) -> None:
        """
        Fetch the facet counts for all facets with post count > 0
        and set the choices on the field.

        Cannot use PostTag.objects.annotate here because the group by clause
        would be wrong (GROUP BY "cast_posttag"."id" instead of "tag"."id")
        """
        self.facet_counts = self.fetch_facet_counts(queryset, Tag.objects.all())
        choices = self.transform_facet_counts_to_choices(self.facet_counts)
        self.set_field_choices(choices)


class PostFilterset(django_filters.FilterSet):
    """
    A filterset for posts. It is used to filter the posts faceted navigation
    style. The filterset facets are configured via the CAST_FILTERSET_FACETS setting.

    The main reason why this code is confusing is that the facets are used
    as the choices for the filterset fields. But the facets are only available
    if the queryset is filtered. So the choices of the fields need to be set
    after the queryset is filtered.
    """

    search = django_filters.CharFilter(field_name="search", method="fulltext_search", label="Search")
    date = django_filters.DateFromToRangeFilter(
        field_name="visible_date",
        label="Date",
        widget=django_filters.widgets.DateRangeWidget(  # type: ignore
            attrs={"type": "date", "placeholder": "YYYY/MM/DD"}
        ),  # type: ignore
    )
    # FIXME Maybe use ModelMultipleChoiceFilter for categories? Couldn't get it to work for now, though.
    #   - one problem was that after setting choices via the choices parameter, Django randomly
    #     complained about models not being available before app start etc.
    category_facets = CategoryFacetFilter(
        field_name="category_facets",
        label="Categories",
        # choices do not need to be set, since they are transported from facet counts
        # into the extra dict of the field via CountChoicesMixin
        widget=CountFacetWidget(attrs={"class": "cast-date-facet-container"}),
    )
    tag_facets = TagFacetFilter(
        field_name="tag_facets",
        label="Tags",
        # choices do not need to be set, since they are transported from facet counts
        # into the extra dict of the field via CountChoicesMixin
        widget=CountFacetWidget(attrs={"class": "cast-date-facet-container"}),
    )
    date_facets = DateFacetFilter(
        field_name="date_facets",
        label="Date Facets",
        widget=CountFacetWidget(attrs={"class": "cast-date-facet-container"}),
    )
    o = django_filters.OrderingFilter(
        fields=(("visible_date", "visible_date"),),
        field_labels={"visible_date": "Date"},
    )

    class Meta:
        fields = appsettings.CAST_FILTERSET_FACETS

    def __init__(
        self,
        data: QueryDict | None = None,
        queryset: models.QuerySet | None = None,
    ):
        if data is None:
            data = QueryDict("")
        if queryset is None:
            from cast.models.pages import Post

            queryset = Post.objects.none()
        super().__init__(data=data, queryset=queryset)
        # Remove filters which are not configured in the settings
        configured_filters = set(appsettings.CAST_FILTERSET_FACETS)
        for filter_name in self.filters.copy().keys():
            if filter_name not in configured_filters:
                del self.filters[filter_name]
        if queryset.exists():
            self.set_facet_counts(self.qs)
        self.remove_form_fields_that_should_be_hidden()

    def set_facet_counts(self, queryset: models.QuerySet) -> None:
        facet_queryset = queryset
        for filter_name, post_filter in self.filters.items():
            if hasattr(post_filter, "set_facet_counts"):
                post_filter.set_facet_counts(facet_queryset)
                self.form.fields[filter_name] = post_filter.field
        # this is needed to update the bound form fields with the new choices
        delattr(self, "_form")

    def remove_form_fields_that_should_be_hidden(self) -> None:
        """
        Remove form fields which should be hidden. For example facets fields with no
        facet with count > 0.
        """
        for name, post_filter in self.filters.items():
            if getattr(post_filter, "hide_form_field", False):
                del self.form.fields[name]

    @staticmethod
    def fulltext_search(queryset: PageQuerySet, _name: str, value: str) -> models.QuerySet:
        return queryset.search(value).get_queryset()
