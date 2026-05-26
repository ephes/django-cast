"""Admin helper views for podcast contributors."""

from typing import Any

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET
from wagtail.snippets.permissions import user_can_access_snippets

from ..models import Contributor, ContributorLink


@require_GET
def link_options(request: HttpRequest) -> JsonResponse:
    """Return link select options for one contributor."""
    if not user_can_access_snippets(request.user, [Contributor]):
        return JsonResponse({"links": []}, status=403)

    try:
        contributor_id = int(request.GET.get("contributor_id", ""))
    except (TypeError, ValueError):
        links = ContributorLink.objects.none()
    else:
        links = ContributorLink.objects.filter(contributor_id=contributor_id).select_related("contributor")

    data: dict[str, list[dict[str, Any]]] = {
        "links": [
            {
                "value": str(link.pk),
                "text": str(link),
                "contributorId": str(link.contributor_id),
            }
            for link in links.order_by("sort_order", "pk")
        ]
    }
    return JsonResponse(data)
