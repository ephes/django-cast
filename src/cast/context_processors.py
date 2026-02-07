from typing import TypedDict

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError
from django.forms import ChoiceField
from django.http import HttpRequest

from .forms import SelectThemeForm
from .models import TemplateBaseDirectory
from .models.theme import get_template_base_dir

DEFAULT_TEMPLATE_BASE_DIR = "does_not_exist"


class SiteTemplateBaseDirContext(TypedDict):
    cast_site_template_base_dir: str
    cast_base_template: str
    template_base_dir: str
    theme_form: SelectThemeForm
    template_base_dir_choices: list[tuple[str, str]]
    next_url: str
    has_selectable_themes: bool


def site_template_base_dir(request: HttpRequest) -> SiteTemplateBaseDirContext:
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

    # Provide theme-switching context globally.
    # Use get_template_base_dir which respects session/query-param overrides.
    try:
        template_base_dir = get_template_base_dir(request, site_template_base_dir_name)
    except (ObjectDoesNotExist, DatabaseError):
        template_base_dir = site_template_base_dir_name

    theme_form = SelectThemeForm(
        initial={
            "template_base_dir": template_base_dir,
            "next": request.get_full_path(),
        }
    )
    field = theme_form.fields["template_base_dir"]
    assert isinstance(field, ChoiceField)
    choices: list[tuple[str, str]] = list(field.choices)  # type: ignore[arg-type]

    return {
        "cast_site_template_base_dir": site_template_base_dir_name,
        "cast_base_template": f"cast/{site_template_base_dir_name}/base.html",
        "template_base_dir": template_base_dir,
        "theme_form": theme_form,
        "template_base_dir_choices": choices,
        "next_url": request.get_full_path(),
        "has_selectable_themes": len(choices) > 1,
    }
