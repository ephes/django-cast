from typing import Union

from django.conf import settings
from django.db.models.signals import post_delete
from wagtail.images import get_image_model
from wagtail.images.signal_handlers import post_delete_file_cleanup

CAST_COMMENTS_ENABLED: bool = getattr(settings, "CAST_COMMENTS_ENABLED", False)
CAST_CUSTOM_THEMES: list[tuple[str, str]] = []
CHOOSER_PAGINATION: int = getattr(settings, "CHOOSER_PAGINATION", 10)
MENU_ITEM_PAGINATION: int = getattr(settings, "MENU_ITEM_PAGINATION", 20)
POST_LIST_PAGINATION: int = getattr(settings, "POST_LIST_PAGINATION", 5)
DELETE_WAGTAIL_IMAGES: bool = getattr(settings, "DELETE_WAGTAIL_IMAGES", True)
CAST_FILTERSET_FACETS: list[str] = getattr(
    settings, "CAST_FILTERSET_FACETS", ["search", "date", "date_facets", "category_facets", "tag_facets"]
)

SettingValue = Union[str, bool, int]


def set_default_if_not_set(setting_name: str, default_value: SettingValue) -> None:
    if getattr(settings, setting_name, None) is None:
        setattr(settings, setting_name, default_value)


DEFAULT_VALUES: list[tuple[str, SettingValue]] = [
    ("SITE_ID", 1),
    ("WAGTAIL_SITE_NAME", "Cast"),
    ("CRISPY_TEMPLATE_PACK", "bootstrap4"),
    ("CRISPY_ALLOWED_TEMPLATE_PACKS", "bootstrap4"),
]


def init_cast_settings() -> None:
    if not DELETE_WAGTAIL_IMAGES:
        # Have a way to deactivate wagtails post_delete_file_cleanup
        # which deletes the file physically when developing against S3
        # cast has to be after wagtail in INSTALLED_APPS for this to work
        post_delete.disconnect(post_delete_file_cleanup, sender=get_image_model())

    for setting_name, default_value in DEFAULT_VALUES:
        set_default_if_not_set(setting_name, default_value)
