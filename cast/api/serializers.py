import logging

from rest_framework import serializers

from ..models import Audio, Video

logger = logging.getLogger(__name__)


class VideoSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="cast:api:video_detail")
    poster = serializers.ImageField(read_only=True, allow_empty_file=True)
    poster_thumbnail = serializers.ImageField(read_only=True, allow_empty_file=True)

    class Meta:
        model = Video
        fields = ("id", "url", "original", "poster", "poster_thumbnail")


class AudioSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="cast:api:audio_detail")
    podlove = serializers.HyperlinkedIdentityField(view_name="cast:api:audio_podlove_detail")

    class Meta:
        model = Audio
        fields = ("id", "name", "file_formats", "url", "podlove", "mp3")


class AudioPodloveSerializer(serializers.HyperlinkedModelSerializer):
    audio = serializers.ListField()
    chapters = serializers.ListField()
    duration = serializers.CharField(source="duration_str")
    link = serializers.URLField(source="episode_url")

    class Meta:
        model = Audio
        fields = ("title", "subtitle", "audio", "duration", "chapters", "link")
