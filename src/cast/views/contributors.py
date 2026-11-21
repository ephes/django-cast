"""Admin helper views for podcast contributors."""

from typing import Any

from django.db.models import F
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET
from wagtail.snippets.permissions import user_can_access_snippets

from ..models import Contributor


@require_GET
def link_options(request: HttpRequest) -> JsonResponse:
    """Return link select options for one contributor."""
    empty_data: dict[str, str | list[dict[str, Any]]] = {
        "defaultRole": "",
        "defaultLinkId": "",
        "links": [],
    }
    if not user_can_access_snippets(request.user, [Contributor]):
        return JsonResponse(empty_data, status=403)

    try:
        contributor_id = int(request.GET.get("contributor_id", ""))
    except (TypeError, ValueError):
        return JsonResponse(empty_data)

    contributor = Contributor.objects.only("display_name", "default_role").filter(pk=contributor_id).first()
    if contributor is None:
        return JsonResponse(empty_data)

    ordered_links = list(
        contributor.links.only("id", "contributor", "service").order_by(F("sort_order").asc(nulls_last=True), "pk")
    )

    data: dict[str, str | list[dict[str, Any]]] = {
        "defaultRole": contributor.default_role,
        "defaultLinkId": str(ordered_links[0].pk) if ordered_links else "",
        "links": [
            {
                "value": str(link.pk),
                "text": str(link),
                "contributorId": str(link.contributor_id),
            }
            for link in ordered_links
        ],
    }
    return JsonResponse(data)
