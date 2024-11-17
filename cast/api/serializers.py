import json
import logging
from typing import Literal, Union

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
    version = serializers.SerializerMethodField()
    show = serializers.SerializerMethodField()
    audio = serializers.ListField()
    chapters = serializers.ListField()
    duration = serializers.CharField(source="duration_str")
    link = serializers.URLField(source="episode_url")
    transcripts = serializers.SerializerMethodField()

    class Meta:
        model = Audio
        fields = ("version", "show", "title", "subtitle", "audio", "duration", "chapters", "link", "transcripts")

    def get_show(self, _instance: Audio) -> dict:
        post = self.context.get("post")  # Get the Post object from the context
        if post is None:
            return {}
        episode = post.specific
        podcast = post.blog.specific
        metadata = {
            "title": podcast.title,
            "subtitle": podcast.subtitle,
            "summary": podcast.search_description,  # FIXME is this correct?
            "link": podcast.full_url,
        }
        context = self.context.copy()
        if episode.cover_image is not None:
            context["cover_image_url"] = episode.cover_image.file.url
        cover_image_context = episode.get_cover_image_context(context, podcast)
        metadata["poster"] = cover_image_context["cover_image_url"]
        return metadata

    @staticmethod
    def get_version(_instance: Audio) -> int:
        return 5

    @staticmethod
    def get_transcripts(instance: Audio) -> list[dict]:
        if not hasattr(instance, "transcript"):
            return []
        transcript = instance.transcript
        if transcript.podlove is None:
            return []
        # Open the file and load its contents as JSON
        with transcript.podlove.open("r") as file:
            try:
                data = json.load(file)  # assumes the file content is JSON
                try:
                    transcripts = data["transcripts"]
                except KeyError:
                    # maybe DOTe instead of Podlove -> empty list
                    transcripts = []
                return transcripts
            except json.JSONDecodeError:
                return []


class SimpleBlogSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="cast:api:facet-counts-detail")

    class Meta:
        model = Blog
        fields = ("id", "url")


FacetName = Literal["date_facets", "category_facets", "tag_facets"]
FacetValueName = Literal["slug", "name", "count"]
FacetList = list[dict[FacetValueName, Union[str, int]]]
FacetCounts = dict[FacetName, FacetList]


class FacetCountSerializer(SimpleBlogSerializer):
    facet_counts = serializers.SerializerMethodField()

    class Meta:
        model = Blog
        fields = ("id", "url", "facet_counts")

    def get_facet_counts(self, instance: Blog) -> FacetCounts:
        """
        Facet counts have the following format:
        {
            "facet_name": [
                {
                    "slug": slug,
                    "name": name,
                    "count": count,
                },
            ],
        }
        """
        get_params = self.context["request"].GET.copy()
        filterset = instance.get_filterset(get_params)

        # transform date facets
        date_facets: FacetList = []
        for date, count in filterset.filters["date_facets"].facet_counts.items():
            year_month: str = date.strftime("%Y-%m")
            date_facets.append({"slug": year_month, "name": year_month, "count": count})

        # transform category facets
        category_facets: FacetList = []
        for slug, (name, count) in filterset.filters["category_facets"].facet_counts.items():
            category_facets.append({"slug": slug, "name": name, "count": count})

        # transform tag facets
        tag_facets: FacetList = []
        for slug, (name, count) in filterset.filters["tag_facets"].facet_counts.items():
            tag_facets.append({"slug": slug, "name": name, "count": count})

        return {
            "date_facets": date_facets,
            "category_facets": category_facets,
            "tag_facets": tag_facets,
        }
