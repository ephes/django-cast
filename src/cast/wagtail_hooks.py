"""Wagtail hooks for django-cast admin integration.

Registers custom admin URLs, menu items, and rich-text link handling
for Audio, Video, Transcript, and Contributor media types. Also
registers a Tags snippet viewset for CRUD operations on ``taggit.Tag``
from the Wagtail admin sidebar.
"""

from collections.abc import Iterator, Mapping, MutableMapping
from contextvars import ContextVar
from typing import Any, TypeVar, overload
from urllib.parse import urlencode

from django.http import HttpRequest
from django.urls import include, path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from taggit.models import Tag
from wagtail import hooks
from wagtail.admin.action_menu import ActionMenuItem
from wagtail.admin.menu import MenuItem
from wagtail.admin.panels import FieldPanel
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy, CollectionPermissionPolicy
from wagtail.rich_text.pages import PageLinkHandler
from wagtail.snippets.models import register_snippet
from wagtail.snippets.permissions import user_can_access_snippets
from wagtail.snippets.views.snippets import SnippetViewSet

from .admin_urls import audio, contributors, transcript, video, voxhelm
from .models import Audio, Contributor, Episode, Transcript, Video
from .transcripts.generation_status import get_transcript_generation_status_context
from .views.voxhelm import user_can_generate_transcript_for_episode
from .voxhelm import voxhelm_configured

_T = TypeVar("_T")


@hooks.register("register_admin_urls")
def register_admin_urls() -> list:
    """Register admin URL namespaces for Audio, Video, and Transcript choosers and CRUD views."""
    return [
        path("audio/", include((audio, "castaudio"), namespace="castaudio")),
        path("media/", include((video, "castvideo"), namespace="castvideo")),
        path("contributors/", include((contributors, "cast-contributors"), namespace="cast-contributors")),
        path("transcript/", include((transcript, "cast-transcript"), namespace="cast-transcript")),
        path("voxhelm/", include((voxhelm, "cast-voxhelm"), namespace="cast-voxhelm")),
    ]


class VideoMenuItem(MenuItem):
    """Admin sidebar menu item for Video management, visible to users with video permissions."""

    def is_shown(self, request: HttpRequest) -> bool:
        permission_policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")
        return permission_policy.user_has_any_permission(request.user, ["add", "change", "delete"])


@hooks.register("register_admin_menu_item")
def register_video_menu_item() -> VideoMenuItem:
    """Register the Video menu item in the Wagtail admin sidebar."""
    return VideoMenuItem(
        _("Video"),
        reverse("castvideo:index"),
        name="video",
        icon_name="desktop",
        order=300,
    )


class AudioMenuItem(MenuItem):
    """Admin sidebar menu item for Audio management, visible to users with audio permissions."""

    def is_shown(self, request: HttpRequest) -> bool:
        permission_policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")
        return permission_policy.user_has_any_permission(request.user, ["add", "change", "delete"])


@hooks.register("register_admin_menu_item")
def register_audio_menu_item() -> AudioMenuItem:
    """Register the Audio menu item in the Wagtail admin sidebar."""
    return AudioMenuItem(
        _("Audio"),
        reverse("castaudio:index"),
        name="audio",
        icon_name="media",
        order=300,
    )


class TranscriptMenuItem(MenuItem):
    """Admin sidebar menu item for Transcript management, visible to users with transcript permissions."""

    def is_shown(self, request: HttpRequest) -> bool:
        permission_policy = CollectionPermissionPolicy(Transcript)
        return permission_policy.user_has_any_permission(request.user, ["add", "change", "delete"])


@hooks.register("register_admin_menu_item")
def register_transcript_menu_item() -> TranscriptMenuItem:
    """Register the Transcript menu item in the Wagtail admin sidebar."""
    return TranscriptMenuItem(
        _("Transcript"),
        reverse("cast-transcript:index"),
        name="transcript",
        icon_name="edit",
        order=300,
    )


@hooks.register("insert_editor_js")
def editor_js_audio_and_video_chooser_urls() -> str:
    """
    This hook is used to insert the audio and video chooser urls. This
    simple code stopped working in Wagtail 6.1:
        <script>
            window.chooserUrls = '{0}';
        </script>
    Throwing this error:
        TypeError: Cannot set properties of undefined (setting 'audioChooser')
            at edit/:100:45
    I don't know why, and I don't have time to investigate. So I'm setting
    both urls in one hook and it works again.
    """
    return format_html(
        """
        <script>
            window.chooserUrls = {{}};
            window.chooserUrls.audioChooser = '{0}';
            window.chooserUrls.videoChooser = '{1}';
        </script>
        """,
        reverse("castaudio:chooser"),
        reverse("castvideo:chooser"),
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


class ContributorMenuItem(MenuItem):
    """Admin sidebar menu item for Contributor snippets."""

    def is_shown(self, request: HttpRequest) -> bool:
        return user_can_access_snippets(request.user, [Contributor])


@hooks.register("register_admin_menu_item")
def register_contributor_menu_item() -> ContributorMenuItem:
    """Register the Contributor snippet list in the Wagtail admin sidebar."""
    return ContributorMenuItem(
        _("Contributors"),
        reverse("wagtailsnippets_cast_contributor:list"),
        name="contributors",
        icon_name="group",
        order=210,
    )


class GenerateEpisodeTranscriptMenuItem(ActionMenuItem):
    label = _("Generate transcript")
    name = "action-generate-transcript"
    icon_name = "doc-full"
    template_name = "cast/wagtail/voxhelm_generate_transcript_action.html"

    def is_shown(self, context: Mapping[str, Any]) -> bool:
        page = context.get("page")
        if context.get("view") != "edit" or not isinstance(page, Episode):
            return False
        if not voxhelm_configured(request_or_site=context["request"]):
            return False
        return user_can_generate_transcript_for_episode(request=context["request"], episode=page)

    def get_url(self, parent_context: Mapping[str, Any]) -> str:
        page = parent_context["page"]
        return reverse("cast-voxhelm:generate_episode", args=(page.pk,))

    def get_context_data(self, parent_context: Mapping[str, Any]) -> dict[str, Any]:
        context = super().get_context_data(parent_context)
        url = context["url"]
        separator = "&" if "?" in url else "?"
        context["action_url"] = f"{url}{separator}{urlencode({'next': parent_context['request'].get_full_path()})}"
        page = parent_context["page"]
        audio = getattr(page, "podcast_audio", None)
        if isinstance(audio, Audio):
            status_context = get_transcript_generation_status_context(audio=audio)
            context["transcript_generation_active"] = status_context["transcript_generation_active"]
        else:
            context["transcript_generation_active"] = False
        return context


@hooks.register("register_page_action_menu_item")
def register_generate_episode_transcript_menu_item() -> GenerateEpisodeTranscriptMenuItem:
    return GenerateEpisodeTranscriptMenuItem(order=70)


class PageLinkHandlerWithCache(PageLinkHandler):
    """
    This is a custom PageLinkHandler that has a cache to store urls
    for internal pages. This is useful when you have all the pages
    anyway in a repository, and you don't want to hit the database
    while rendering links.
    """

    class _ContextLocalCache(MutableMapping[int, str]):
        """Context-local cache storage to avoid leaking URLs between requests."""

        _missing = object()
        _storage: ContextVar[dict[int, str] | None] = ContextVar("page_link_handler_cache", default=None)

        def _get_cache(self) -> dict[int, str]:
            cache = self._storage.get()
            if cache is None:
                cache = {}
                self._storage.set(cache)
            return cache

        def __getitem__(self, key: int) -> str:
            return self._get_cache()[key]

        def __setitem__(self, key: int, value: str) -> None:
            self._get_cache()[key] = value

        def __delitem__(self, key: int) -> None:
            del self._get_cache()[key]

        def __iter__(self) -> Iterator[int]:
            return iter(self._get_cache())

        def __len__(self) -> int:
            return len(self._get_cache())

        def __contains__(self, key: object) -> bool:
            return key in self._get_cache()

        def clear(self) -> None:
            self._storage.set({})

        @overload
        def pop(self, key: int) -> str: ...  # pragma: no cover

        @overload
        def pop(self, key: int, default: str) -> str: ...  # pragma: no cover

        @overload
        def pop(self, key: int, default: _T) -> str | _T: ...  # pragma: no cover

        def pop(self, key: int, default: object = _missing) -> object:
            if default is self._missing:
                return self._get_cache().pop(key)
            return self._get_cache().pop(key, default)

    cache: MutableMapping[int, str] = _ContextLocalCache()

    @classmethod
    def cache_url(cls, page_id: int, url: str) -> None:
        cls.cache[page_id] = url

    @classmethod
    def expand_db_attributes(cls, attrs: dict[str, Any]) -> str:
        if (cached_url := cls.cache.get(int(attrs["id"]))) is not None:
            return f'<a href="{cached_url}">'
        return super().expand_db_attributes(attrs)

    @classmethod
    def expand_db_attributes_many(cls, attrs_list: list[dict[str, Any]]) -> list[str]:
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
def register_page_link(features: Any) -> None:
    """Replace Wagtail's default page link handler with the cache-aware variant."""
    features.register_link_type(PageLinkHandlerWithCache)
