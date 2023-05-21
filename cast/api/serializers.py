import logging

from rest_framework import serializers

from ..models import Audio, Blog, Video

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


class SimpleBlogSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="cast:api:facet-counts-detail")

    class Meta:
        model = Blog
        fields = ("id", "url")


class FacetCountSerializer(SimpleBlogSerializer):
    facet_counts = serializers.SerializerMethodField()

    class Meta:
        model = Blog
        fields = ("id", "url", "facet_counts")

    def get_facet_counts(self, instance: Blog) -> dict[str, int]:
        get_params = self.context["request"].GET.copy()
        filterset = instance.get_filterset(get_params)
        facet_counts = filterset.facet_counts["year_month"]
        result = {}
        for date, count in facet_counts.items():
            result[date.strftime("%Y-%m")] = count
        return result
