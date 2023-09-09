from django.views import csrf, defaults

from cast.models import TemplateBaseDirectory


def get_template_base_directory(request):
    """Get the template base directory for the current request, ignoring all exceptions"""
    try:
        return TemplateBaseDirectory.for_request(request).name
    except Exception:
        # If we can't get the template base directory from the database,
        # just use the default one.
        return "plain"


def get_template_name(request, base_template_name):
    """Get the template name for the current request"""
    template_base_dir = get_template_base_directory(request)
    return f"cast/{template_base_dir}/{base_template_name}"


def page_not_found(request, exception):
    """Just call the default page_not_found view, but with a custom template"""
    return defaults.page_not_found(request, exception, template_name=get_template_name(request, "404.html"))


def server_error(request):
    """Just call the default server_error view, but with a custom template"""
    return defaults.server_error(request, template_name=get_template_name(request, "500.html"))


def bad_request(request, exception):
    """Just call the default bad_request view, but with a custom template"""
    return defaults.bad_request(request, exception, template_name=get_template_name(request, "400.html"))


def permission_denied(request, exception):
    """Just call the default permission_denied view, but with a custom template"""
    return defaults.permission_denied(request, exception, template_name=get_template_name(request, "403.html"))


def csrf_failure(request, reason=""):
    """Just call the default csrf_failure view, but with a custom template"""
    return csrf.csrf_failure(request, reason, template_name=get_template_name(request, "403_csrf.html"))
