from django.contrib.auth.models import User
from django.http import HttpRequest
from django_htmx.middleware import HtmxDetails


class AuthenticatedHttpRequest(HttpRequest):
    user: User


class HtmxHttpRequest(HttpRequest):
    htmx: HtmxDetails
