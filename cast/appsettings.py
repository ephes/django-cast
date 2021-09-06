from django.conf import settings


CAST_COMMENTS_ENABLED = getattr(settings, "CAST_COMMENTS_ENABLED", False)
CHOOSER_PAGINATION = getattr(settings, "CHOOSER_PAGINATION", 10)
MENU_ITEM_PAGINATION = getattr(settings, "MENU_ITEM_PAGINATION", 20)
