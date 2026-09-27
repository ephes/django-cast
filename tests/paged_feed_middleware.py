"""Test-only middleware that exercises the paged feed final response hook.

Placed inside SessionMiddleware/CsrfViewMiddleware, so their real response hooks
set the cookies this middleware provokes via request headers.
"""

from django.http import HttpResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.utils import timezone

LITERAL_COOKIE = "literal=1; Path=/"


class ProvokingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.headers.get("X-Test-Session"):
            request.session["provoked"] = True
        if request.headers.get("X-Test-Csrf"):
            get_token(request)
        if zone := request.headers.get("X-Test-Timezone"):
            timezone.activate(zone)
        response = self.get_response(request)
        if vary := request.headers.get("X-Test-Vary"):
            response["Vary"] = vary
        if request.headers.get("X-Test-Validators"):
            response["Last-Modified"] = "Wed, 01 Jan 2025 00:00:00 GMT"
            response["Expires"] = "Wed, 01 Jan 2025 00:05:00 GMT"
        if request.headers.get("X-Test-Set-Cookie"):
            # Set directly as a header, bypassing response.cookies.
            response["Set-Cookie"] = LITERAL_COOKIE
        if request.headers.get("X-Test-Replace") == "stream":
            return StreamingHttpResponse([b"replaced"])
        if request.headers.get("X-Test-Replace"):
            replaced = HttpResponse(b"replaced")
            replaced["ETag"] = 'W/"replaced"'
            return replaced
        return response
