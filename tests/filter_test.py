from django.http import QueryDict

from cast.filters import DateFacetWidget, get_facet_counts


def test_date_facet_widget_render():
    dfw = DateFacetWidget()
    dfw.choices = [("foo", ("bar", "baz"))]
    dfw.data = {}
    html = dfw.render("foo", "bar")
    assert "foo" in html
    assert "bar" in html
    assert "baz" in html


def test_date_facet_widget_if_options(mocker):
    mocker.patch("cast.filters.DateFacetWidget.render_options", return_value=False)
    dfw = DateFacetWidget()
    html = dfw.render("foo", "bar")
    assert "foo" not in html


def test_get_facet_counts(mocker):
    get_selected_facet = mocker.patch("cast.filters.get_selected_facet")
    mocker.patch("cast.filters.PostFilterset")
    _ = get_facet_counts(None, [mocker.MagicMock()])
    # only isinstance because the initial filterset_data dict is modified
    assert isinstance(get_selected_facet.call_args[0][0], dict)


def test_active_pagination_is_removed_from_date_facet_filter():
    dfw = DateFacetWidget()
    dfw.data = QueryDict("page=3")
    QueryDict
    option = dfw.render_option("name", set(), "value", "label")
    assert "page=3" not in option


def test_selected_date_facet_is_in_hidden_input():
    dfw = DateFacetWidget()
    dfw.data = QueryDict("date_facets=2018-12")
    option = dfw.render_option("date_facets", {"2018-12"}, "2018-12", "2018-12 (3)")
    assert '<input type="hidden" name="date_facets" value="2018-12">' in option
