import os
import sys
from importlib.util import find_spec
from pathlib import Path

from . import base as base_settings
from .base import *  # noqa


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "fi6y_c!w#4+16srq_%z+(dj=7d8&5+reik+_171*=e8(0(157x"

# SECURITY WARNING: define the correct hosts in production!
ALLOWED_HOSTS = ["*"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

INSTALLED_APPS.extend(  # noqa
    [
        "django_extensions",
    ]
)

CAST_ENABLE_STYLEGUIDE = True


def _env_flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no"}


REPO_ROOT = base_settings.BASE_DIR.parent  # Assumes example/ lives inside the repo.
SIBLING_ROOT = REPO_ROOT.parent


def _add_repo_to_path(repo_path: Path) -> None:
    if repo_path.is_dir():
        sys.path.insert(0, str(repo_path))


_add_repo_to_path(SIBLING_ROOT / "cast-bootstrap5")
_add_repo_to_path(SIBLING_ROOT / "cast-vue")
CAST_VITE_DEV_MODE = _env_flag("CAST_VITE_DEV_MODE", "1")
CAST_BOOTSTRAP5_VITE_DEV_MODE = _env_flag("CAST_BOOTSTRAP5_VITE_DEV_MODE", "1")
CAST_VUE_VITE_DEV_MODE = _env_flag("CAST_VUE_VITE_DEV_MODE", "1")
CAST_STYLEGUIDE_REMOTE_MEDIA = _env_flag("CAST_STYLEGUIDE_REMOTE_MEDIA", "1")
CAST_STYLEGUIDE_IMAGE_SOURCE_URLS = [
    "https://wersdoerfer.de/blogs/ephes_blog/weeknotes-2025-11-03-shipping-steel-iq/",
    "https://wersdoerfer.de/blogs/ephes_blog/weeknotes-2025-08-18/",
]
CAST_STYLEGUIDE_VIDEO_SOURCE_URL = "https://wersdoerfer.de/blogs/ephes_blog/weeknotes-2025-02-03/"
CAST_STYLEGUIDE_PODCAST_SOURCE_URL = "https://python-podcast.de/show/platonismus-und-python-data-class-builders/"
CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL = (
    "https://python-podcast.de/show/platonismus-und-python-data-class-builders/transcript/"
)
CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS = 12
CAST_STYLEGUIDE_TRANSCRIPT_EXCERPT_SEGMENTS = 2
CAST_STYLEGUIDE_IMAGE_LIMIT = 40
CAST_STYLEGUIDE_REMOTE_TIMEOUT = 20
CAST_STYLEGUIDE_GENERATE_RENDITIONS = False
CAST_STYLEGUIDE_BODY_GALLERY_LIMIT = 2

DJANGO_VITE = {
    "cast": {
        "dev_mode": CAST_VITE_DEV_MODE,
        "dev_server_port": 5173,
        "static_url_prefix": "" if CAST_VITE_DEV_MODE else "cast/vite",
        "manifest_path": REPO_ROOT / "src" / "cast" / "static" / "cast" / "vite" / "manifest.json",
    }
}

CAST_CUSTOM_THEMES: list[tuple[str, str]] = []

if find_spec("cast_bootstrap5") is not None:
    import cast_bootstrap5

    INSTALLED_APPS.extend(  # noqa
        [
            "crispy_bootstrap5",
            "cast_bootstrap5.apps.CastBootstrap5Config",
        ]
    )
    CRISPY_TEMPLATE_PACK = "bootstrap5"
    CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
    CAST_CUSTOM_THEMES.append(("bootstrap5", "Bootstrap 5"))

    bootstrap5_manifest = (
        Path(cast_bootstrap5.__file__).resolve().parent / "static" / "cast_bootstrap5" / "vite" / "manifest.json"
    )
    DJANGO_VITE["cast-bootstrap5"] = {
        "dev_mode": CAST_BOOTSTRAP5_VITE_DEV_MODE,
        "dev_server_port": 5174,
        "static_url_prefix": "" if CAST_BOOTSTRAP5_VITE_DEV_MODE else "cast_bootstrap5/vite",
        "manifest_path": bootstrap5_manifest,
    }

if find_spec("cast_vue") is not None:
    import cast_vue

    INSTALLED_APPS.extend(  # noqa
        [
            "cast_vue.apps.CastVueConfig",
        ]
    )
    CAST_CUSTOM_THEMES.append(("vue", "Cast Vue"))

    vue_manifest = Path(cast_vue.__file__).resolve().parent / "static" / "cast_vue" / "vite" / "manifest.json"
    DJANGO_VITE["cast_vue"] = {
        "dev_mode": CAST_VUE_VITE_DEV_MODE,
        "dev_server_port": 5175,
        "static_url_prefix": "" if CAST_VUE_VITE_DEV_MODE else "cast_vue/vite",
        "manifest_path": vue_manifest,
    }


try:
    from .local import *  # noqa
except ImportError:
    pass
