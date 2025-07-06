from pathlib import Path

from django.conf import settings
from django.db import models
from django.template import engines
from django.template.loaders.base import Loader as BaseLoader
from django.utils.translation import gettext_lazy as _
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting

from ..views import HtmxHttpRequest


def get_required_template_names() -> list[str]:
    """
    Return a list of template names that have to be present in a theme. Not just
    a constant because maybe it's possible to calculate this dynamically in the
    future.
    """
    return [
        "blog_list_of_posts.html",
        "post.html",
        "post_body.html",
        "episode.html",
    ]


def is_compatible_template_loader(template_loader: BaseLoader) -> bool:
    """
    Return True if the template loader is compatible with theme discovery.
    """
    return hasattr(template_loader, "get_dirs")


def get_template_directories() -> list[Path]:
    """
    Return a list of template directories from all template loaders.
    Only filesystem loaders are supported.
    """
    template_directories = []
    for engine in engines.all():
        for template_loader in engine.engine.template_loaders:  # type: ignore
            if is_compatible_template_loader(template_loader):
                for template_directory in template_loader.get_dirs():
                    if isinstance(template_directory, str):
                        template_directory = Path(template_directory)
                    template_directories.append(template_directory)
    return template_directories


def is_cast_template_base_dir_candidate(base_dir: Path, required_template_names: list[str]) -> bool:
    """
    Return True if base_dir is a candidate for a template base directory which means
    it contains all required template files from required_template_names.
    """
    for template_name in required_template_names:
        if not (base_dir / template_name).exists():
            # a required template does not exist -> base_dir is not a candidate
            return False
    return True


def get_template_base_dir_candidates(
    template_directories: list[Path], required_template_names: list[str] = get_required_template_names()
) -> list[str]:
    """
    Return a list of template base directory candidates containing the required
    template file names.
    """
    directory_matches: set[Path] = set()
    if len(required_template_names) == 0:
        # nothing required -> nothing to find -> return early
        return []
    required_template_name = required_template_names[0]
    for template_directory in template_directories:
        for directory_match in list(template_directory.glob(f"**/cast/**/{required_template_name}")):
            directory_matches.add(directory_match.parent)
    return [dm.name for dm in directory_matches if is_cast_template_base_dir_candidate(dm, required_template_names)]


class TemplateName(models.TextChoices):
    BOOTSTRAP4 = "bootstrap4", _("Bootstrap 4")
    PLAIN = "plain", _("Just HTML")


def get_template_base_dir_choices() -> list[tuple[str, str]]:
    """
    Return a list of choices for the template base directory setting.
    """
    # handle predefined choices
    choices: list[tuple[str, str]] = []
    seen: set[str] = set()
    for template_name in TemplateName:
        choices.append((template_name.value, str(template_name.label)))  # type: ignore[misc]
        seen.add(template_name.value)  # type: ignore[misc]

    # handle custom choices via settings
    for template_name, display_name in getattr(settings, "CAST_CUSTOM_THEMES", []):
        if template_name not in seen:
            choices.append((template_name, display_name))
            seen.add(template_name)

    # search for template base directories
    template_directories = get_template_directories()
    template_base_dir_candidates = get_template_base_dir_candidates(template_directories)
    for candidate in template_base_dir_candidates:
        if candidate not in seen:
            choices.append((candidate, candidate))

    return choices


def get_template_base_dir(request: HtmxHttpRequest, pre_selected: str | None) -> str:
    if hasattr(request, "session") and (template_base_dir := request.session.get("template_base_dir")) is not None:
        return template_base_dir
    if pre_selected is not None:
        return pre_selected
    else:
        return TemplateBaseDirectory.for_request(request).name


@register_setting
class TemplateBaseDirectory(BaseSiteSetting):
    """
    The base directory for templates. Makes it possible to use different
    templates for different sites / change look and feel of the site from
    the wagtail admin.
    """

    name: models.CharField = models.CharField(
        choices=get_template_base_dir_choices(),
        max_length=128,
        default=TemplateName.BOOTSTRAP4,
        help_text=_(
            "The theme to use for this site implemented as a template base directory. "
            "It's possible to overwrite this setting for each blog."
            "If you want to use a custom theme, you have to create a new directory "
            "in your template directory named cast/<your-theme-name>/ and put all "
            "required templates in there."
        ),
    )
