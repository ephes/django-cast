from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from django.http import HttpRequest

from .forms import SelectThemeForm
from .models import TemplateBaseDirectory
from .models.theme import get_template_base_dir

DEFAULT_TEMPLATE_BASE_DIR = "does_not_exist"


def site_template_base_dir(request: HttpRequest) -> dict[str, Any]:
    """
    Add the name of the template base directory to the context.
    Add the complete base template path to the context for convenience.
    Also provide theme-switching context (form, choices, next_url) so that
    theme selectors work on every page, not only blog index pages.
    """
    if hasattr(request, "cast_site_template_base_dir"):
        site_template_base_dir_name = request.cast_site_template_base_dir
    else:
        try:
            site_template_base_dir_name = TemplateBaseDirectory.for_request(request).name
        except (ObjectDoesNotExist, DatabaseError):
            site_template_base_dir_name = DEFAULT_TEMPLATE_BASE_DIR

    context: dict[str, Any] = {
        "cast_site_template_base_dir": site_template_base_dir_name,
        "cast_base_template": f"cast/{site_template_base_dir_name}/base.html",
    }

    # Provide theme-switching context globally.
    # Use get_template_base_dir which respects session/query-param overrides.
    try:
        template_base_dir = get_template_base_dir(request, site_template_base_dir_name)  # type: ignore[arg-type]
    except (ObjectDoesNotExist, DatabaseError):
        template_base_dir = site_template_base_dir_name

    theme_form = SelectThemeForm(
        initial={
            "template_base_dir": template_base_dir,
            "next": request.get_full_path(),
        }
    )
    choices = theme_form.fields["template_base_dir"].choices  # type: ignore[union-attr, attr-defined]

    context["template_base_dir"] = template_base_dir
    context["theme_form"] = theme_form
    context["template_base_dir_choices"] = choices
    context["next_url"] = request.get_full_path()
    context["has_selectable_themes"] = len(choices) > 1

    return context
