from django.conf import settings

CAST_COMMENTS_ENABLED: bool = getattr(settings, "CAST_COMMENTS_ENABLED", False)
CHOOSER_PAGINATION: int = getattr(settings, "CHOOSER_PAGINATION", 10)
MENU_ITEM_PAGINATION: int = getattr(settings, "MENU_ITEM_PAGINATION", 20)
POST_LIST_PAGINATION: int = getattr(settings, "POST_LIST_PAGINATION", 5)
DELETE_WAGTAIL_IMAGES: bool = getattr(settings, "DELETE_WAGTAIL_IMAGES", True)
