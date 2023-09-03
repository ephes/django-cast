import logging
from collections import OrderedDict
from typing import Any, cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet
from django.http import JsonResponse
from django.urls import reverse
from django.views.generic import CreateView
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.api.v2.router import WagtailAPIRouter
from wagtail.api.v2.views import PagesAPIViewSet
from wagtail.images.api.v2.views import ImagesAPIViewSet

from ..filters import PostFilterset
from ..forms import SelectThemeForm, VideoForm
from ..models import (
    Audio,
    Blog,
    SpamFilter,
    Video,
    get_template_base_dir,
    get_template_base_dir_choices,
)
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
    max_page_size = 10000


class VideoListView(generics.ListCreateAPIView):
    serializer_class = VideoSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet[Video]:
        user = self.request.user
        qs = Video.objects.all().filter(user=user)
        return qs.order_by("-created")


class VideoDetailView(generics.RetrieveDestroyAPIView):
    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    permission_classes = (IsAuthenticated,)


class AudioListView(generics.ListCreateAPIView):
    serializer_class = AudioSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self) -> QuerySet[Audio]:
        user = self.request.user
        qs = Audio.objects.all().filter(user=user)
        return qs.order_by("-created")


class AudioDetailView(generics.RetrieveDestroyAPIView):
    queryset = Audio.objects.all()
    serializer_class = AudioSerializer
    permission_classes = (IsAuthenticated,)


class AudioPodloveDetailView(generics.RetrieveAPIView):
    queryset = Audio.objects.all()
    serializer_class = AudioPodloveSerializer

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        if (episode_id := request.query_params.get("episode_id")) is not None:
            try:
                episode_id = int(episode_id)
                instance.set_episode_id(episode_id)
            except (ValueError, TypeError):
                pass
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class FacetCountListView(generics.ListCreateAPIView):
    serializer_class = SimpleBlogSerializer
    queryset = Blog.objects.all().live().order_by("-first_published_at")
    pagination_class = StandardResultsSetPagination


class FacetCountsDetailView(generics.RetrieveAPIView):
    queryset = Blog.objects.all()
    serializer_class = FacetCountSerializer


class CommentTrainingDataView(APIView):
    permission_classes = (IsAuthenticated,)

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

    def post(self, request: Request, *args, **kwargs) -> Response:
        new_theme_slug = request.data.get("theme_slug", None)
        form = SelectThemeForm({"template_base_dir": new_theme_slug})
        if not form.is_valid():
            return Response({"error": "Theme slug is invalid"}, status=status.HTTP_400_BAD_REQUEST)

        request = cast(HtmxHttpRequest, request)
        set_template_base_dir(request, form.cleaned_data["template_base_dir"])

        return Response({"message": "Theme updated successfully"}, status=status.HTTP_200_OK)


class FilteredPagesAPIViewSet(PagesAPIViewSet):
    def get_filtered_queryset(self) -> QuerySet:
        # allow additional query parameters from PostFilterset + use_post_filter flag
        additional_query_params = PostFilterset.Meta.fields + ["use_post_filter"] + ["date_before", "date_after"]
        self.known_query_parameters: set = self.known_query_parameters.union(additional_query_params)
        # remove search parameter from query params because it won't work with PagesAPIViewSet
        # in combination with PostFilterset. But doing full text search on PostFilterset will work.
        original_get_params = self.request.GET.copy()
        get_params = self.request.GET.copy()
        if "search" in get_params:
            del get_params["search"]
        self.request.GET = get_params
        queryset = super().get_queryset()
        filterset = PostFilterset(data=original_get_params, queryset=queryset)
        return filterset.qs

    def get_queryset(self):
        if self.request.GET.dict().get("use_post_filter", "false") == "true":
            return self.get_filtered_queryset()
        return super().get_queryset()


# Wagtail API
wagtail_api_router = WagtailAPIRouter("cast:api:wagtail")
wagtail_api_router.register_endpoint("pages", FilteredPagesAPIViewSet)
wagtail_api_router.register_endpoint("images", ImagesAPIViewSet)
