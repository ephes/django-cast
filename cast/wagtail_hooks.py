from django.urls import include, path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.core.permission_policies.collections import (
    CollectionOwnershipPermissionPolicy,
)

from .admin_urls import audio, video
from .models import Audio, Video


@hooks.register("register_admin_urls")
def register_admin_urls():
    return [
        path("audio/", include((audio, "castaudio"), namespace="castaudio")),
        path("media/", include((video, "castvideo"), namespace="castvideo")),
    ]


class VideoMenuItem(MenuItem):
    def is_shown(self, request):
        permission_policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")
        return permission_policy.user_has_any_permission(request.user, ["add", "change", "delete"])


@hooks.register("register_admin_menu_item")
def register_video_menu_item():
    return VideoMenuItem(
        _("Video"),
        reverse("castvideo:index"),
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
        reverse("castvideo:chooser"),
    )


class AudioMenuItem(MenuItem):
    def is_shown(self, request):
        permission_policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")
        return permission_policy.user_has_any_permission(request.user, ["add", "change", "delete"])


@hooks.register("register_admin_menu_item")
def register_audio_menu_item():
    return AudioMenuItem(
        _("Audio"),
        reverse("castaudio:index"),
        name="audio",
        classnames="icon icon-media",
        order=300,
    )


@hooks.register("insert_editor_js")
def editor_js_audio():
    return format_html(
        """
        <script>
            window.chooserUrls.audioChooser = '{0}';
        </script>
        """,
        reverse("castaudio:chooser"),
    )
