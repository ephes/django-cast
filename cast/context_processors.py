from django.http import HttpRequest

from .models import TemplateBaseDirectory


def site_template_base_dir(request: HttpRequest) -> dict[str, str]:
    """
    Add the name of the template base directory to the context.
    Add the complete base template path to the context for convenience.
    """
    site_template_base_dir_name = TemplateBaseDirectory.for_request(request).name
    return {
        "cast_site_template_base_dir": site_template_base_dir_name,
        "cast_base_template": f"cast/{site_template_base_dir_name}/base.html",
    }
