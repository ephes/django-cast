from django.conf import settings

CAST_COMMENTS_ENABLED = getattr(settings, "CAST_COMMENTS_ENABLED", False)
