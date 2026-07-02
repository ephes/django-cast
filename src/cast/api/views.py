import hashlib
import json
import logging
from collections import OrderedDict
from typing import Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.views.generic import CreateView
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.api.v2.router import WagtailAPIRouter
from wagtail.api.v2.views import PagesAPIViewSet
from wagtail.images.api.v2.views import ImagesAPIViewSet

from ..audio_access import authorize_audio_access, page_grants_audio_access, page_is_unrestricted_public
from ..filters import PostFilterset
from ..forms import SelectThemeForm, VideoForm
from ..models import (
    Audio,
    Blog,
    Post,
    SpamFilter,
    Video,
    get_template_base_dir,
    get_template_base_dir_choices,
)
from ..modal_facet_counts import get_modal_facet_counts
from ..player import build_player_payload
from ..podlove import build_podlove_player_config
from ..views import HtmxHttpRequest
from ..views.theme import set_template_base_dir
from .serializers import (
    AudioPodloveSerializer,
    AudioSerializer,
    FacetCountSerializer,
    SimpleBlogSerializer,
    VideoSerializer,
)
from .viewmixins import AddRequestUserMixin, FileUploadResponseMixin

logger = logging.getLogger(__name__)


@api_view(["GET"])
def api_root(request: Request) -> Response:
    """
    Show API contents.
    If you add any object types, add them here!
    """
    root_api_urls = (
        # ("images", request.build_absolute_uri(reverse("cast:api:image_list"))),
        # ("galleries", request.build_absolute_uri(reverse("cast:api:gallery_list"))),
        ("videos", request.build_absolute_uri(reverse("cast:api:video_list"))),
        ("audios", request.build_absolute_uri(reverse("cast:api:audio_list"))),
        ("comment_training_data", request.build_absolute_uri(reverse("cast:api:comment-training-data"))),
        ("themes", request.build_absolute_uri(reverse("cast:api:theme-list"))),
        ("pages", request.build_absolute_uri(reverse("cast:api:wagtail:pages:listing"))),
        ("images", request.build_absolute_uri(reverse("cast:api:wagtail:images:listing"))),
        ("facet_counts", request.build_absolute_uri(reverse("cast:api:facet-counts-list"))),
    )
    return Response(OrderedDict(root_api_urls))


class VideoCreateView(LoginRequiredMixin, AddRequestUserMixin, FileUploadResponseMixin, CreateView):  # type: ignore
    model = Video
    form_class = VideoForm
    user_field_name = "user"


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 40
    page_size_query_param = "pageSize"
    max_page_size = 200


class VideoListView(generics.ListCreateAPIView):
    serializer_class = VideoSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet[Video]:
        user = self.request.user
        qs = Video.objects.all().filter(user=user)
        return qs.order_by("-created")


class VideoDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = VideoSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet[Video]:
        user = self.request.user
        return Video.objects.filter(user=user)


class AudioListView(generics.ListCreateAPIView):
    serializer_class = AudioSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet[Audio]:
        user = self.request.user
        qs = Audio.objects.all().filter(user=user)
        return qs.order_by("-created")


class AudioDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = AudioSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet[Audio]:
        user = self.request.user
        return Audio.objects.filter(user=user)


class AudioPodloveDetailView(generics.RetrieveAPIView):
    queryset = Audio.objects.all()
    serializer_class = AudioPodloveSerializer
    permission_classes = (AllowAny,)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        post_id = kwargs.get("post_id")
        episode_id = request.query_params.get("episode_id")
        # Every supplied anchor must authorize for this audio. ``episode_id`` is not
        # only an access check: it also drives the serialized episode link, so an
        # unvalidated value could surface a draft/restricted episode of the same
        # audio. Authorizing each anchor keeps the access gate and the rendered
        # context consistent; a mismatched or non-public anchor is a 404.
        anchors = [anchor for anchor in (post_id, episode_id) if anchor is not None]
        if anchors:
            for anchor in anchors:
                authorize_audio_access(request, audio=instance, explicit_anchor_id=anchor)
        else:
            authorize_audio_access(request, audio=instance)
        if episode_id is not None:
            instance.set_episode_id(int(episode_id))

        # Retrieve post_id from kwargs and add it to context
        if not hasattr(self, "request"):
            # those attributes need to be set before calling get_serializer_context
            self.request = request
            self.format_kwarg = None
        context = self.get_serializer_context()
        post_id = kwargs.get("post_id")
        if post_id:
            post = get_object_or_404(Post, pk=post_id)
            context["post"] = post

        serializer = self.get_serializer(instance, context=context)
        return Response(serializer.data)


class AudioPlayerTranscriptView(generics.RetrieveAPIView):
    """Public, sanitized transcript-cue source for the custom audio player.

    The custom player loads the transcript lazily, fetching this endpoint once the
    first time the reader opens the Transcript panel. Returns the normalized,
    sanitized ``{"cues": [...]}`` shape — never the raw Podlove file.
    """

    queryset = Audio.objects.all()
    permission_classes = (AllowAny,)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        audio = self.get_object()
        post_id = kwargs.get("post_id") or request.query_params.get("post_id")
        post = self._get_authorized_post(post_id, audio, request)
        if post is None:
            # Do not leak unsanitized data for a missing/mismatched context.
            raise Http404("No transcript available for this audio in the given context.")
        payload = build_player_payload(audio, post=post, request=request, inline_transcript=False)
        cues = payload["transcript"]["cues"]

        # Cache so re-opening the transcript after navigation doesn't refetch.
        # A strong ETag over the *sanitized* cues stays correct across transcript
        # edits and contributor/speaker-mapping changes; Cache-Control lets the
        # browser serve from its HTTP cache within the window (no request), and a
        # cheap 304 covers revalidation after it. The content is already public.
        serialized = json.dumps(cues, ensure_ascii=False, sort_keys=True)
        etag = f'"{hashlib.sha256(serialized.encode("utf-8")).hexdigest()}"'
        if_none_match = request.headers.get("If-None-Match", "")
        candidates = {token.strip() for token in if_none_match.split(",") if token.strip()}
        if etag in candidates or "*" in candidates:
            response: Response = Response(status=status.HTTP_304_NOT_MODIFIED)
        else:
            response = Response({"cues": cues})
        response["ETag"] = etag
        self._set_cache_headers(response, post)
        return response

    @staticmethod
    def _set_cache_headers(response: Response, post: Post) -> None:
        specific = getattr(post, "specific", post)
        if page_is_unrestricted_public(specific):
            response["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
            return
        response["Cache-Control"] = "private, no-store"
        patch_vary_headers(response, ("Cookie", "Authorization"))

    @staticmethod
    def _get_authorized_post(post_id: Any, audio: Audio, request: Request) -> Post | None:
        """Resolve the owning post when the request may read its transcript.

        Grants access when the post references the audio and is either publicly
        viewable (live + view restrictions satisfied) or editable by the
        requester (Wagtail preview / unpublished drafts).
        """
        if post_id is None:
            return None
        try:
            post = Post.objects.get(pk=int(post_id))
        except (Post.DoesNotExist, ValueError, TypeError):
            return None
        if page_grants_audio_access(post.specific, audio, request):
            return post
        return None


class PlayerConfig(generics.RetrieveAPIView):
    permission_classes = (AllowAny,)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        template_base_dir = get_template_base_dir(request, None)
        color_scheme = request.query_params.get("color_scheme")
        config = build_podlove_player_config(template_base_dir=template_base_dir, color_scheme=color_scheme)
        return Response(config)


class FacetCountListView(generics.ListAPIView):
    serializer_class = SimpleBlogSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (AllowAny,)

    def get_queryset(self) -> QuerySet[Blog]:
        return Blog.objects.all().live().public().order_by("-first_published_at")


class FacetCountsDetailView(generics.RetrieveAPIView):
    serializer_class = FacetCountSerializer
    permission_classes = (AllowAny,)

    def get_queryset(self) -> QuerySet[Blog]:
        return Blog.objects.all().live().public()

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        if request.query_params.get("mode") == "modal":
            blog = self.get_object()
            payload = get_modal_facet_counts(blog, request.query_params)
            return Response(payload)
        return super().retrieve(request, *args, **kwargs)


class CommentTrainingDataView(APIView):
    permission_classes = (IsAdminUser,)

    @staticmethod
    def get(request, _format: Any = None) -> JsonResponse:
        """
        Return training data for comment classification.
        """
        train = SpamFilter.get_training_data_comments()
        return JsonResponse(train, safe=False)


class ThemeListView(generics.ListAPIView):
    """
    Return a list of available themes. Mark the currently selected theme.
    This is used by the theme switcher for the vue frontend for example.
    """

    permission_classes = (AllowAny,)

    def get_queryset(self) -> None:
        return None

    def list(self, request: Request, *args, **kwargs) -> Response:
        choices = get_template_base_dir_choices()
        request = cast(HtmxHttpRequest, request)
        template_base_dir = get_template_base_dir(request, None)
        themes = []
        for slug, name in choices:
            selected = slug == template_base_dir
            themes.append({"slug": slug, "name": name, "selected": selected})
        result = {"items": themes}
        return Response(result)


class UpdateThemeView(APIView):
    """
    Update the selected theme.
    """

    permission_classes = (AllowAny,)

    def post(self, request: Request, *args, **kwargs) -> Response:
        if not isinstance(request.data, dict):
            return Response({"error": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)

        new_theme_slug = request.data.get("theme_slug", None)
        form = SelectThemeForm({"template_base_dir": new_theme_slug})
        if not form.is_valid():
            return Response({"error": "Theme slug is invalid"}, status=status.HTTP_400_BAD_REQUEST)

        request = cast(HtmxHttpRequest, request)
        set_template_base_dir(request, form.cleaned_data["template_base_dir"])

        return Response({"message": "Theme updated successfully"}, status=status.HTTP_200_OK)


class RemoveNullBytesMixin:
    """
    Workaround for query parameters containing null bytes. There
    should be proper input validation in Wagtail APIViewSets, but
    this is a quick fix for now.
    """

    request: HttpRequest

    def cleanup_null_bytes(self):
        for key, value in self.request.GET.items():
            if "\x00" in value:
                mutable_copy = self.request.GET.copy()
                mutable_copy[key] = value.replace("\x00", "")
                self.request.GET = mutable_copy

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        self.cleanup_null_bytes()
        # pycharm gets it, mypy doesn't
        return super().filter_queryset(queryset)  # type: ignore


class FilteredPagesAPIViewSet(RemoveNullBytesMixin, PagesAPIViewSet):
    def _extend_known_query_parameters(self) -> None:
        additional_query_params = PostFilterset.Meta.fields + [
            "use_post_filter",
            "date_before",
            "date_after",
            "template_base_dir",
            "render_for_feed",
            "theme",
        ]
        known_query_parameters = cast(set[str], getattr(self, "known_query_parameters", set()))
        setattr(self, "known_query_parameters", known_query_parameters.union(additional_query_params))

    def _apply_template_base_dir_override(self) -> None:
        template_base_dir = self.request.GET.get("template_base_dir") or self.request.GET.get("theme")
        if not template_base_dir:
            return
        choices = {slug for slug, _name in get_template_base_dir_choices()}
        if template_base_dir not in choices:
            return
        setattr(self.request, "cast_template_base_dir", template_base_dir)
        if hasattr(self.request, "_request"):
            setattr(self.request._request, "cast_template_base_dir", template_base_dir)

    def get_filtered_queryset(self) -> QuerySet:
        # allow additional query parameters from PostFilterset + use_post_filter flag
        self._extend_known_query_parameters()
        self._apply_template_base_dir_override()
        # remove search parameter from query params because it won't work with PagesAPIViewSet
        # in combination with PostFilterset. But doing full text search on PostFilterset will work.
        original_get_params = self.request.GET.copy()
        get_params = self.request.GET.copy()
        if "search" in get_params:
            del get_params["search"]
        self.request.GET = get_params  # type: ignore
        queryset = super().get_queryset()
        filterset = PostFilterset(data=original_get_params, queryset=queryset)
        return filterset.qs

    def get_queryset(self):
        self._extend_known_query_parameters()
        self._apply_template_base_dir_override()
        if self.request.GET.dict().get("use_post_filter", "false") == "true":
            return self.get_filtered_queryset()
        return super().get_queryset()


class CastImagesAPIViewSet(RemoveNullBytesMixin, ImagesAPIViewSet):
    pass


# Wagtail API
wagtail_api_router = WagtailAPIRouter("cast:api:wagtail")
wagtail_api_router.register_endpoint("pages", FilteredPagesAPIViewSet)
wagtail_api_router.register_endpoint("images", CastImagesAPIViewSet)
