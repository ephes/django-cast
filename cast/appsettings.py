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


def init_cast_settings():
    print("init_cast_settings: ", DELETE_WAGTAIL_IMAGES)
    if not DELETE_WAGTAIL_IMAGES:
        # Have a way to deactivate wagtails post_delete_file_cleanup
        # which deletes the file physically when developing against S3
        # cast has to be after wagtail in INSTALLED_APPS for this to work
        post_delete.disconnect(post_delete_file_cleanup, sender=get_image_model())
