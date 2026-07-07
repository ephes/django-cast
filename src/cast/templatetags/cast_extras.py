from typing import cast

from django import template
from django.http import HttpRequest
from django.template import Context

register = template.Library()


@register.simple_tag(takes_context=True)
def remove_filter_url(context: Context, param_name: str) -> str:
    """Build URL with the named filter param (and page) removed."""
    request = cast(HttpRequest, context["request"])
    params = request.GET.copy()
    params.pop(param_name, None)
    params.pop("page", None)  # always reset pagination when removing a filter
    query = params.urlencode()
    return f"?{query}" if query else request.path
