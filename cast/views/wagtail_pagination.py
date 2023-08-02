from typing import Union

from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from django.http import HttpRequest

from ..appsettings import MENU_ITEM_PAGINATION
from ..models import Audio, Video

DEFAULT_PAGE_KEY = "p"

pagination_template = "wagtailadmin/shared/ajax_pagination_nav.html"


def paginate(
    request: HttpRequest,
    items: Union[QuerySet[Audio], QuerySet[Video]],
    page_key: str = DEFAULT_PAGE_KEY,
    per_page: int = MENU_ITEM_PAGINATION,
) -> tuple[Paginator, Page]:
    paginator: Paginator = Paginator(items, per_page)
    page = paginator.get_page(request.GET.get(page_key))
    return paginator, page
