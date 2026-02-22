import warnings
from pathlib import Path

from django.conf import settings
from django.db import models
from django.http import HttpRequest
from django.template import engines
from django.template.loaders.base import Loader as BaseLoader
from django.utils.translation import gettext_lazy as _
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting

# Process-lifetime cache for theme choices.  Themes are discovered from the
# filesystem and settings at import/first-call time; changes require a worker
# restart.  Stored as an immutable tuple to prevent accidental mutation.
_template_base_dir_choices_cache: tuple[tuple[str, str], ...] | None = None


def _clear_template_base_dir_choices_cache() -> None:
    global _template_base_dir_choices_cache  # noqa: PLW0603
    _template_base_dir_choices_cache = None


def get_strictly_required_template_names() -> list[str]:
    """
    Return the template names that *must* exist for a theme to be discovered.
    Missing any of these causes the theme directory to be skipped entirely.
    """
    return [
        "blog_list_of_posts.html",
        "post.html",
        "post_body.html",
        "episode.html",
    ]


def get_soft_required_template_names() -> list[str]:
    """
    Return template names that are part of the theme contract but only
    produce a DeprecationWarning when missing (staged enforcement).

    In a future release these will become strictly required and missing
    ones will block theme discovery.
    """
    return [
        "base.html",
        "pagination.html",
        "400.html",
        "403.html",
        "403_csrf.html",
        "404.html",
        "500.html",
    ]


def get_required_template_names() -> list[str]:
    """
    Return *all* template names that the theme contract requires.
    This is the union of strictly required and soft-required templates.
    """
    return get_strictly_required_template_names() + get_soft_required_template_names()


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


def check_theme_soft_requirements(base_dir: Path) -> list[str]:
    """
    Check whether *base_dir* contains the soft-required templates.
    Returns a list of missing template names.  For each missing template a
    ``DeprecationWarning`` is emitted so theme authors get early notice.
    """
    missing: list[str] = []
    for template_name in get_soft_required_template_names():
        if not (base_dir / template_name).exists():
            missing.append(template_name)
            warnings.warn(
                f"Theme '{base_dir.name}' is missing '{template_name}'. "
                f"This template will become required in a future release.",
                DeprecationWarning,
                stacklevel=2,
            )
    return missing


def get_template_base_dir_candidates(
    template_directories: list[Path],
    required_template_names: list[str] | None = None,
) -> list[str]:
    """
    Return a list of template base directory candidates containing the required
    template file names.

    Discovery uses only the *strictly* required templates so that themes
    missing the newer soft-required templates are still found (with warnings).
    """
    if required_template_names is None:
        required_template_names = get_strictly_required_template_names()
    directory_matches: set[Path] = set()
    if len(required_template_names) == 0:
        # nothing required -> nothing to find -> return early
        return []
    required_template_name = required_template_names[0]
    for template_directory in template_directories:
        for directory_match in list(template_directory.glob(f"**/cast/**/{required_template_name}")):
            directory_matches.add(directory_match.parent)
    candidates = []
    for dm in directory_matches:
        if is_cast_template_base_dir_candidate(dm, required_template_names):
            check_theme_soft_requirements(dm)
            candidates.append(dm.name)
    return candidates


class TemplateName(models.TextChoices):
    BOOTSTRAP4 = "bootstrap4", _("Bootstrap 4")
    PLAIN = "plain", _("Just HTML")


def get_template_base_dir_choices() -> list[tuple[str, str]]:
    """
    Return a list of choices for the template base directory setting.
    """
    global _template_base_dir_choices_cache  # noqa: PLW0603
    if _template_base_dir_choices_cache is not None:
        return list(_template_base_dir_choices_cache)

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

    _template_base_dir_choices_cache = tuple(choices)
    return choices


def get_template_base_dir(request: HttpRequest, pre_selected: str | None) -> str:
    """
    Resolve the active theme for the current request.

    **Theme switching precedence** (highest wins):

    1. ``request.cast_template_base_dir`` — internal override set by code
       (e.g. styleguide preview).
    2. ``?theme=X`` / ``?template_base_dir=X`` query param — temporary
       preview for the current request only.  Does **not** modify the
       session.  Used for theme comparison, styleguide, and development.
    3. Django session value (``request.session["template_base_dir"]``) —
       the persistent user choice, set via POST to ``/cast/select-theme/``.
    4. *pre_selected* argument — typically the blog-level
       ``template_base_dir`` field.
    5. Site-level ``TemplateBaseDirectory`` Wagtail setting — global
       default fallback.

    The Django session is the **canonical source of truth** for the active
    theme, regardless of whether the theme is server-rendered (SSR) or a
    single-page app (SPA).  After a full page reload *without* a
    ``?theme`` query param, the rendered theme always matches the session
    value (or the blog/site default if no session value exists).
    """
    if (override := getattr(request, "cast_template_base_dir", None)) is not None:
        return override
    if hasattr(request, "GET"):
        template_base_dir = request.GET.get("template_base_dir") or request.GET.get("theme")
        if template_base_dir:
            choices = {slug for slug, _name in get_template_base_dir_choices()}
            if template_base_dir in choices:
                return template_base_dir
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
