from django.db import IntegrityError
from django.http import HttpRequest

from .models import TemplateBaseDirectory

DEFAULT_TEMPLATE_BASE_DIR = "does_not_exist"


def site_template_base_dir(request: HttpRequest) -> dict[str, str]:
    """
    Add the name of the template base directory to the context.
    Add the complete base template path to the context for convenience.
    """
    if hasattr(request, "cast_site_template_base_dir"):
        site_template_base_dir_name = request.cast_site_template_base_dir
    else:
        try:
            site_template_base_dir_name = TemplateBaseDirectory.for_request(request).name
        except (TemplateBaseDirectory.DoesNotExist, IntegrityError):
            # If the site template base directory does not exist, use the default
            # need to catch IntegrityError because of Wagtail5 support
            site_template_base_dir_name = DEFAULT_TEMPLATE_BASE_DIR
    return {
        "cast_site_template_base_dir": site_template_base_dir_name,
        "cast_base_template": f"cast/{site_template_base_dir_name}/base.html",
    }
