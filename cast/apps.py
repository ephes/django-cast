from django.apps import AppConfig
from django.db.models.signals import post_delete
from wagtail.images import get_image_model
from wagtail.images.signal_handlers import post_delete_file_cleanup

from . import appsettings


class CastConfig(AppConfig):
    name: str = "cast"

    def ready(self) -> None:
        if not appsettings.DELETE_WAGTAIL_IMAGES:
            # Have a way to deactivate wagtails post_delete_file_cleanup
            # which deletes the file physically when developing against S3
            # cast has to be after wagtail in INSTALLED_APPS for this to work
            post_delete.disconnect(post_delete_file_cleanup, sender=get_image_model())
