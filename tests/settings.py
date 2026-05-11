# ruff: noqa: F403,F405
from cast.apps import CAST_APPS
from cast.settings import *  # noqa: F403

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
