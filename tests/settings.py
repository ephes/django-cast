import os
from pathlib import Path
from typing import Any

import django_stubs_ext

from cast.apps import CAST_APPS

django_stubs_ext.monkeypatch()

ROOT_DIR = Path(__file__).resolve().parent.parent / "src" / "cast"
APPS_DIR = ROOT_DIR / "cast"
TESTS_DIR = Path(__file__).resolve().parent

DEBUG = False
USE_TZ = True

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "mbmcf(_0(y@^nlf6w#1nq%s7&nzcfvx#ok$iwu8)i^d+^96h*="

TEST_DATABASE_NAME = os.environ.get("CAST_TEST_DB", "tests/test_database.sqlite3")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": TEST_DATABASE_NAME,
        # if this is not set, an in memory database is used
        # for tests by default _get_test_db_name
        "TEST": {"NAME": TEST_DATABASE_NAME},
    },
}

ROOT_URLCONF = "tests.urls"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sites",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django.contrib.messages",
] + list(CAST_APPS)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

# only gets invoked for python manage.py test
TEST_RUNNER = "cast.runner.PytestTestRunner"

# STATIC FILE CONFIGURATION
# ------------------------------------------------------------------------------
# See: https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(ROOT_DIR / "staticfiles")

# See: https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"

# See: https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(ROOT_DIR / "static")]

# See: https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA CONFIGURATION
# ------------------------------------------------------------------------------
# Keep test uploads out of src/cast/media; tests/conftest.py cleans this path.
MEDIA_ROOT = str(TESTS_DIR / "media")
CAST_PRIVATE_MEDIA_ROOT = str(TESTS_DIR / "private-media")

# See: https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"


# TEMPLATE CONFIGURATION
# ------------------------------------------------------------------------------
# See: https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES: list[dict[str, Any]] = [
    {
        # See: https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # See: https://docs.djangoproject.com/en/dev/ref/settings/#template-dirs
        "DIRS": [str(APPS_DIR / "templates")],
        "OPTIONS": {
            # See: https://docs.djangoproject.com/en/dev/ref/settings/#template-debug
            "debug": DEBUG,
            # See: https://docs.djangoproject.com/en/dev/ref/templates/api/#loader-types
            "loaders": [
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
            # See: https://docs.djangoproject.com/en/dev/ref/settings/#std-setting-TEMPLATES-OPTIONS-context_processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                # Your stuff: custom template context processors go here
            ],
        },
    }
]

# TEMPLATE LOADERS
# ------------------------------------------------------------------------------
# Keep templates in memory so tests run faster
TEMPLATES[0]["OPTIONS"]["loaders"] = [
    [
        "django.template.loaders.cached.Loader",
        [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    ]
]

# Comments
COMMENTS_APP = "cast.comments"

# For Django >= 3.2 - auto field
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# This provided a 70% speedup
# use a faster password hasher - dont do this in production, it's only for testing
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Use in memory cache for tests
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# crispy forms
CRISPY_TEMPLATE_PACK = "bootstrap4"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap4"

# view handling csrf failures
CSRF_FAILURE_VIEW = "cast.views.defaults.csrf_failure"

# django_vite
DJANGO_VITE = {
    "cast": {
        "dev_mode": True,
    }
}

# Wagtail
WAGTAILADMIN_BASE_URL = "/cms"
WAGTAILIMAGES_MAX_UPLOAD_SIZE = 30 * 1024 * 1024
ALLOWED_HOSTS = ["testserver", "localhost", "example.com"]

TASKS = {
    "default": {
        "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
        # django-tasks 0.7, used by Wagtail 7.0, defers immediate tasks until
        # transaction commit by default. Tests assert search results before
        # pytest-django's outer transaction commits, so execute immediately.
        "ENQUEUE_ON_COMMIT": False,
    },
    "cast_transcripts": {
        "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
        "ENQUEUE_ON_COMMIT": False,
    },
}
