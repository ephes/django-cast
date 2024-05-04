from django.http import HttpRequest
from django.urls import include, path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from taggit.models import Tag
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.admin.panels import FieldPanel
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy
from wagtail.rich_text.pages import PageLinkHandler
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from .admin_urls import audio, video
from .models import Audio, Video


@hooks.register("register_admin_urls")
def register_admin_urls() -> list:
    return [
        path("audio/", include((audio, "castaudio"), namespace="castaudio")),
        path("media/", include((video, "castvideo"), namespace="castvideo")),
    ]


class VideoMenuItem(MenuItem):
    def is_shown(self, request: HttpRequest) -> bool:
        permission_policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")
        return permission_policy.user_has_any_permission(request.user, ["add", "change", "delete"])


@hooks.register("register_admin_menu_item")
def register_video_menu_item() -> VideoMenuItem:
    return VideoMenuItem(
        _("Video"),
        reverse("castvideo:index"),
        name="video",
        classnames="icon icon-media",
        order=300,
    )


@hooks.register("insert_editor_js")
def editor_js() -> str:
    return format_html(
        """
        <script>
            window.chooserUrls.videoChooser = '{0}';
        </script>
        """,
        reverse("castvideo:chooser"),
    )


class AudioMenuItem(MenuItem):
    def is_shown(self, request: HttpRequest) -> bool:
        permission_policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")
        return permission_policy.user_has_any_permission(request.user, ["add", "change", "delete"])


@hooks.register("register_admin_menu_item")
def register_audio_menu_item() -> AudioMenuItem:
    return AudioMenuItem(
        _("Audio"),
        reverse("castaudio:index"),
        name="audio",
        classnames="icon icon-media",
        order=300,
    )


@hooks.register("insert_editor_js")
def editor_js_audio() -> str:
    return format_html(
        """
        <script>
            window.chooserUrls.audioChooser = '{0}';
        </script>
        """,
        reverse("castaudio:chooser"),
    )


class TagsSnippetViewSet(SnippetViewSet):
    """
    This is a snippet viewset for the taggit Tag model. It is used to
    be able to do crud operations on tags from the admin menu.
    """

    panels = [FieldPanel("name")]  # only show the name field
    model = Tag
    icon = "tag"  # change as required
    add_to_admin_menu = True
    menu_label = "Tags"
    menu_order = 200  # will put in 3rd place (000 being 1st, 100 2nd)
    list_display = ["name", "slug"]
    search_fields = ("name",)


register_snippet(TagsSnippetViewSet)


class PageLinkHandlerWithCache(PageLinkHandler):
    """
    This is a custom PageLinkHandler that has a cache to store urls
    for internal pages. This is useful when you have all the pages
    anyway in a repository, and you don't want to hit the database
    while rendering links.
    """

    cache: dict[int, str] = {}

    @classmethod
    def cache_url(cls, page_id: int, url: str):
        cls.cache[page_id] = url

    @classmethod
    def expand_db_attributes(cls, attrs):
        if (cached_url := cls.cache.get(int(attrs["id"]))) is not None:
            return f'<a href="{cached_url}">'
        return super().expand_db_attributes(attrs)

    @classmethod
    def expand_db_attributes_many(cls, attrs_list: list[dict]) -> list[str]:
        """Required for Wagtail >= 6.1"""
        links, all_cached = [], True
        for attrs in attrs_list:
            if (cached_url := cls.cache.get(int(attrs["id"]))) is not None:
                links.append(f'<a href="{cached_url}">')
            else:
                all_cached = False
                break
        if all_cached:
            return links
        # if not all cached, fallback to the super method
        return super().expand_db_attributes_many(attrs_list)


@hooks.register("register_rich_text_features")
def register_page_link(features):
    features.register_link_type(PageLinkHandlerWithCache)
