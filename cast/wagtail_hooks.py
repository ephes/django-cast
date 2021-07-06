from django.urls import path, include, reverse
from django.utils.translation import gettext_lazy as _

from wagtail.core import hooks
from wagtail.admin.menu import MenuItem

from wagtailmedia.permissions import permission_policy


from . import admin_urls


@hooks.register("register_admin_urls")
def register_admin_urls():
    return [
        path("media/", include((admin_urls, "wagtailmedia"), namespace="castmedia")),
    ]


class VideoMenuItem(MenuItem):
    def is_shown(self, request):
        return permission_policy.user_has_any_permission(
            request.user, ["add", "change", "delete"]
        )


@hooks.register("register_admin_menu_item")
def register_media_menu_item():
    return VideoMenuItem(
        _("Video"),
        reverse("castmedia:index"),
        name="video",
        classnames="icon icon-media",
        order=300,
    )
