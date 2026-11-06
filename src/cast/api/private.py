"""Response policy for authenticated, non-public APIs."""

from typing import Any

from django.utils.cache import patch_cache_control, patch_vary_headers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


class PrivateAPIView(APIView):
    """Require a fresh access check rather than reuse of a stored response."""

    def finalize_response(self, request: Request, response: Response, *args: Any, **kwargs: Any) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)
        patch_cache_control(response, private=True, no_store=True)
        patch_vary_headers(response, ("Cookie", "Authorization"))
        return response
