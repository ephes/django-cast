from __future__ import annotations

from typing import Any

from django.db.models import Q
from rest_framework.request import Request
from rest_framework.response import Response

from ...models import Contributor
from ..views import StandardResultsSetPagination
from .errors import EditorValidationError
from .media import _reject_unsupported_query_params
from .views import EditorAPIView

MAX_CONTRIBUTOR_SLUG_FILTERS = 100


def serialize_contributor(contributor: Contributor) -> dict[str, Any]:
    return {
        "id": contributor.pk,
        "slug": contributor.slug,
        "display_name": contributor.display_name,
        "default_role": contributor.default_role,
        "visible": contributor.visible,
    }


class ContributorListView(EditorAPIView):
    """List contributors that can be assigned to episodes.

    Mirrors the episode admin form, whose contributor select offers every
    contributor to anyone who may edit the episode. Private voice-reference data
    is never exposed.
    """

    required_scopes = {"GET": None}
    pagination_class = StandardResultsSetPagination
    allowed_query_params = {"q", "slug", "page", "pageSize", "format"}

    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _reject_unsupported_query_params(request, self.allowed_query_params)
        slugs = list(dict.fromkeys(request.query_params.getlist("slug")))
        if len(slugs) > MAX_CONTRIBUTOR_SLUG_FILTERS:
            raise EditorValidationError(
                {
                    "slug": [
                        {"code": "too_many", "message": f"Use at most {MAX_CONTRIBUTOR_SLUG_FILTERS} distinct slugs."}
                    ]
                }
            )
        max_length = Contributor._meta.get_field("slug").max_length
        assert max_length is not None
        if any(len(slug) > max_length for slug in slugs):
            raise EditorValidationError(
                {"slug": [{"code": "max_length", "message": f"Each slug must be at most {max_length} characters."}]}
            )

        queryset = Contributor.objects.only("id", "slug", "display_name", "default_role", "visible")
        q = request.query_params.get("q")
        if q:
            queryset = queryset.filter(Q(display_name__icontains=q) | Q(slug__icontains=q))
        if slugs:
            queryset = queryset.filter(slug__in=slugs)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset.order_by("display_name", "id"), request, view=self)
        assert page is not None
        return paginator.get_paginated_response([serialize_contributor(contributor) for contributor in page])
