import os
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
CAST_VITE_DEV_MODE = _env_flag("CAST_VITE_DEV_MODE", "1")
CAST_BOOTSTRAP5_VITE_DEV_MODE = _env_flag("CAST_BOOTSTRAP5_VITE_DEV_MODE", "1")

DJANGO_VITE = {
    "cast": {
        "dev_mode": CAST_VITE_DEV_MODE,
        "dev_server_port": 5173,
        "static_url_prefix": "" if CAST_VITE_DEV_MODE else "cast/vite",
        "manifest_path": REPO_ROOT / "src" / "cast" / "static" / "cast" / "vite" / "manifest.json",
    }
}

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
    CAST_CUSTOM_THEMES = [("bootstrap5", "Bootstrap 5")]

    bootstrap5_manifest = (
        Path(cast_bootstrap5.__file__).resolve().parent / "static" / "cast_bootstrap5" / "vite" / "manifest.json"
    )
    DJANGO_VITE["cast-bootstrap5"] = {
        "dev_mode": CAST_BOOTSTRAP5_VITE_DEV_MODE,
        "dev_server_port": 5174,
        "static_url_prefix": "" if CAST_BOOTSTRAP5_VITE_DEV_MODE else "cast_bootstrap5/vite",
        "manifest_path": bootstrap5_manifest,
    }


try:
    from .local import *  # noqa
except ImportError:
    pass
