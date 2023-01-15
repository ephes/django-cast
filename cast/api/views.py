import logging
from collections import OrderedDict

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.urls import reverse
from django.views.generic import CreateView
from rest_framework import generics
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..forms import VideoForm
from ..models import Audio, SpamFilter, Video
from .serializers import AudioPodloveSerializer, AudioSerializer, VideoSerializer
from .viewmixins import AddRequestUserMixin, FileUploadResponseMixin

logger = logging.getLogger(__name__)


@api_view(["GET"])
def api_root(request):
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
    )
    return Response(OrderedDict(root_api_urls))


class VideoCreateView(LoginRequiredMixin, AddRequestUserMixin, FileUploadResponseMixin, CreateView):
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

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if (episode_id := request.query_params.get("episode_id")) is not None:
            try:
                episode_id = int(episode_id)
                instance.set_episode_id(episode_id)
            except (ValueError, TypeError):
                pass
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class CommentTrainingDataView(APIView):
    permission_classes = (IsAuthenticated,)

    @staticmethod
    def get(request, format=None):
        """
        Return training data for comment classification.
        """
        train = SpamFilter.get_training_data_comments()
        return JsonResponse(train, safe=False)
