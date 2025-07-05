from django.core.paginator import Page, Paginator
from django.db.models import QuerySet
from django.http import HttpRequest

from ..appsettings import MENU_ITEM_PAGINATION
from ..models import Audio, Transcript, Video

DEFAULT_PAGE_KEY = "p"

pagination_template = "wagtailadmin/shared/pagination_nav.html"


def paginate(
    request: HttpRequest,
    items: QuerySet[Audio] | QuerySet[Video] | QuerySet[Transcript],
    page_key: str = DEFAULT_PAGE_KEY,
    per_page: int = MENU_ITEM_PAGINATION,
) -> tuple[Paginator, Page]:
    # if not items.query.order_by:
    #     items = items.order_by("id")
    paginator: Paginator = Paginator(items, per_page)
    page = paginator.get_page(request.GET.get(page_key))
    return paginator, page
