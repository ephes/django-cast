from pathlib import Path

from django.db import models
from django.template import engines
from django.template.loaders.base import Loader as BaseLoader
from django.utils.translation import gettext_lazy as _
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting


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
    choices, predefined = [], set()
    for template_name in TemplateName:
        choices.append((template_name.value, template_name.label))
        predefined.add(template_name.value)

    # search for template base directories
    template_directories = get_template_directories()
    template_base_dir_candidates = get_template_base_dir_candidates(template_directories)
    for candidate in template_base_dir_candidates:
        if candidate not in predefined:
            choices.append((candidate, candidate))

    return choices


@register_setting
class TemplateBaseDirectory(BaseSiteSetting):
    """
    The base directory for templates. Makes it possible to use different
    templates for different sites / change look and feel of the site from
    the wagtail admin.
    """

    name = models.CharField(choices=get_template_base_dir_choices(), max_length=10, default=TemplateName.BOOTSTRAP4)
