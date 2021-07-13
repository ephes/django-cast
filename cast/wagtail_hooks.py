from django.utils.html import format_html
from django.urls import path, include, reverse
from django.utils.translation import gettext_lazy as _

from wagtail.core import hooks
from wagtail.core.permission_policies.collections import CollectionOwnershipPermissionPolicy
from wagtail.admin.menu import MenuItem

from . import admin_urls
from .models import Video


@hooks.register("register_admin_urls")
def register_admin_urls():
    return [
        path("video/", include((admin_urls, "wagtailmedia"), namespace="castmedia")),
    ]


class VideoMenuItem(MenuItem):
    def is_shown(self, request):
        permission_policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")
        return permission_policy.user_has_any_permission(request.user, ["add", "change", "delete"])


@hooks.register("register_admin_menu_item")
def register_media_menu_item():
    return VideoMenuItem(
        _("Video"),
        reverse("castmedia:video_index"),
        name="video",
        classnames="icon icon-media",
        order=300,
    )


@hooks.register("insert_editor_js")
def editor_js():
    return format_html(
        """
        <script>
            window.chooserUrls.videoChooser = '{0}';
        </script>
        """,
        reverse("castmedia:video_chooser"),
    )
