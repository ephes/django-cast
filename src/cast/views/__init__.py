from django.contrib.auth.models import User
from django.http import HttpRequest

from .htmx_helpers import HtmxHttpRequest


class AuthenticatedHttpRequest(HttpRequest):
    user: User


__all__ = [
    "HtmxHttpRequest",
    "AuthenticatedHttpRequest",
]
