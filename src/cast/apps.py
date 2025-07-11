from django.apps import AppConfig


# Apps required by django-cast
CAST_APPS = [
    # Form styling
    "crispy_forms",
    "crispy_bootstrap4",
    # Filtering and API
    "django_filters",
    "django_htmx",
    "rest_framework",
    # Comments system
    "fluent_comments",  # must be before django_comments
    "threadedcomments",
    "django_comments",
    # Vite support
    "django_vite",
    # Wagtail CMS
    "wagtail.api.v2",
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.settings",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    # Wagtail dependencies
    "modelcluster",
    "taggit",
    # Cast itself
    "cast.apps.CastConfig",
]

# Middleware required by django-cast
CAST_MIDDLEWARE = [
    "django_htmx.middleware.HtmxMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
]


class CastConfig(AppConfig):
    name: str = "cast"

    def ready(self) -> None:
        from .appsettings import init_cast_settings

        init_cast_settings()
