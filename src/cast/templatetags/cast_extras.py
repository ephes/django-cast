from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def remove_filter_url(context, param_name):
    """Build URL with the named filter param (and page) removed."""
    request = context["request"]
    params = request.GET.copy()
    params.pop(param_name, None)
    params.pop("page", None)  # always reset pagination when removing a filter
    query = params.urlencode()
    return f"?{query}" if query else request.path
