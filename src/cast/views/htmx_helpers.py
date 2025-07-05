from django.http import HttpRequest
from django_htmx.middleware import HtmxDetails


# Typing pattern recommended by django-stubs:
# https://github.com/typeddjango/django-stubs#how-can-i-create-a-httprequest-thats-guaranteed-to-have-an-authenticated-user
class HtmxHttpRequest(HttpRequest):
    cast_site_template_base_dir: str
    htmx: HtmxDetails
