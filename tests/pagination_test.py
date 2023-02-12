import pytest
from django.core.paginator import Paginator
from django.shortcuts import render
from django.test import RequestFactory


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture
def simple_request(request_factory):
    return request_factory.get("/")


def test_pagination_template_is_not_paginated(simple_request):
    r = render(simple_request, "pagination.html", {})
    html = r.content.decode("utf-8").strip()
    assert html == ""


def test_pagination_template_is_paginated(simple_request):
    r = render(simple_request, "pagination.html", {"is_paginated": True})
    html = r.content.decode("utf-8").strip()
    assert "pagination" in html


def test_pagination_template_is_paginated_long(simple_request):
    paginator = Paginator(range(1000), 2)
    page = paginator.page(9)
    context = {
        "is_paginated": page.has_other_pages(),
        "paginator": paginator,
        "page_obj": page,
        "object_list": page.object_list,
        "page_range": page.paginator.get_elided_page_range(page.number, on_each_side=2, on_ends=1),
    }
    r = render(simple_request, "pagination.html", context)
    html = r.content.decode("utf-8").strip()
    assert "page=1" in html  # first page
    assert "page=500" in html  # last page

    # two ellipsis in the middle which are not links
    ellipsis_items = [line for line in html.splitlines() if "…" in line]
    assert len(ellipsis_items) == 2
    assert (
        '<span class="page-link">…</span>' == ellipsis_items[0].strip()
    )  # ellipsis in the middle which is not a link
