import logging

from collections import OrderedDict

from django.views.generic import CreateView

from django.contrib.auth.mixins import LoginRequiredMixin

from django.urls import reverse

from rest_framework import status
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework.serializers import ListSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination

from .serializers import (
    ImageSerializer,
    VideoSerializer,
    GallerySerializer,
    AudioSerializer,
    AudioPodloveSerializer,
    RequestSerializer,
)

from ..forms import ImageForm, VideoForm

from ..viewmixins import AddRequestUserMixin
from .viewmixins import FileUploadResponseMixin

from ..models import Image, Video, Gallery, Audio, Request

logger = logging.getLogger(__name__)


@api_view(["GET"])
def api_root(request):
    """
    Show API contents.
    If you add any object types, add them here!
    """
    root_api_urls = (
        ("images", request.build_absolute_uri(reverse("cast:api:image_list"))),
        ("galleries", request.build_absolute_uri(reverse("cast:api:gallery_list"))),
        ("videos", request.build_absolute_uri(reverse("cast:api:video_list"))),
        ("audios", request.build_absolute_uri(reverse("cast:api:audio_list"))),
        ("requests", request.build_absolute_uri(reverse("cast:api:request_list"))),
    )
    return Response(OrderedDict(root_api_urls))


class ImageCreateView(
    LoginRequiredMixin, AddRequestUserMixin, FileUploadResponseMixin, CreateView
):
    model = Image
    form_class = ImageForm
    user_field_name = "user"


class VideoCreateView(
    LoginRequiredMixin, AddRequestUserMixin, FileUploadResponseMixin, CreateView
):
    model = Video
    form_class = VideoForm
    user_field_name = "user"


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 40
    page_size_query_param = "pageSize"
    max_page_size = 10000


class ImageListView(generics.ListCreateAPIView):
    serializer_class = ImageSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        user = self.request.user
        qs = Image.objects.all().filter(user=user)
        return qs.order_by("-created")


class ImageDetailView(generics.RetrieveDestroyAPIView):
    queryset = Image.objects.all()
    serializer_class = ImageSerializer
    permission_classes = (IsAuthenticated,)


class VideoListView(generics.ListCreateAPIView):
    serializer_class = VideoSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
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

    def get_queryset(self):
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


class GalleryListView(generics.ListCreateAPIView):
    serializer_class = GallerySerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        user = self.request.user
        qs = Gallery.objects.all().filter(user=user)
        return qs.order_by("-created")


class GalleryDetailView(generics.RetrieveDestroyAPIView):
    queryset = Gallery.objects.all()
    serializer_class = GallerySerializer
    permission_classes = (IsAuthenticated,)


class RequestListView(generics.ListCreateAPIView):
    queryset = Request.objects.all().order_by("-timestamp")
    serializer_class = RequestSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = (IsAuthenticated,)

    def create(self, request, *args, **kwargs):
        """Allow for bulk create via many=True."""
        serializer = self.get_serializer(
            data=request.data, many=isinstance(request.data, list)
        )
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def perform_create(self, serializer):
        """Use bulk_create for request lists, normal model serializer otherwise."""
        if isinstance(serializer, ListSerializer):
            requests = [Request(**d) for d in serializer.validated_data]
            Request.objects.bulk_create(requests)
        else:
            serializer.save()
