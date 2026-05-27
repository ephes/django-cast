import json
import logging
from typing import Any, Literal, Union

from rest_framework import serializers

from ..models import Audio, Blog, Video
from ..transcript_sanitization import (
    podlove_contributors_from_data,
    sanitize_podlove_data,
    strict_public_speaker_labels_for_audio,
)

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
    contributors = serializers.SerializerMethodField()

    class Meta:
        model = Audio
        fields = (
            "version",
            "show",
            "title",
            "subtitle",
            "audio",
            "duration",
            "chapters",
            "link",
            "transcripts",
            "contributors",
        )

    def to_representation(self, instance: Audio) -> dict:
        # Load the Podlove transcript JSON once so the transcripts and
        # contributors fields share a single file read per response.
        raw_podlove_data = self._load_podlove_data(instance)
        post = self.context.get("post")
        episode = getattr(post, "specific", post)
        allowed_speaker_labels = strict_public_speaker_labels_for_audio(instance, episode=episode)
        self._podlove_data = sanitize_podlove_data(raw_podlove_data, allowed_speaker_labels)
        try:
            return super().to_representation(instance)
        finally:
            del self._podlove_data

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
        request = self.context.get("request")
        metadata["poster"] = episode.get_cover_image_poster_url(request=request, blog=podcast)
        return metadata

    @staticmethod
    def get_version(_instance: Audio) -> int:
        return 5

    def _load_podlove_data(self, instance: Audio) -> dict[str, Any]:
        """Return the parsed Podlove transcript JSON for ``instance``.

        Returns an empty dict when there is no transcript, no Podlove file, the
        file is missing from storage, or its content is not a JSON object.
        """
        if not hasattr(instance, "transcript"):
            return {}
        transcript = instance.transcript
        if not transcript.podlove:
            return {}
        try:
            with transcript.podlove.open("r") as file:
                data = json.load(file)  # assumes the file content is JSON
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _podlove_data_for(self, instance: Audio) -> dict[str, Any]:
        """Return the Podlove JSON, reusing the per-response load when available."""
        cached = getattr(self, "_podlove_data", None)
        if cached is not None:
            return cached
        return self._load_podlove_data(instance)

    def get_transcripts(self, instance: Audio) -> list[dict]:
        """Return the Podlove transcript segments for the Podlove Web Player."""
        # maybe DOTe instead of Podlove or no transcript at all -> empty list
        return self._podlove_data_for(instance).get("transcripts", [])

    def get_contributors(self, instance: Audio) -> list[dict[str, str]]:
        """Return Podlove player contributors derived from transcript speaker labels.

        Podlove Web Player resolves a transcript segment's ``speaker`` id against
        the top-level ``contributors`` list and renders ``contributor.name``.
        Contributors are collected in first-appearance order from non-blank
        ``speaker`` and ``voice`` values; the raw label is used as both ``id``
        and ``name`` so it keeps matching the segment ``speaker`` id.
        """
        return podlove_contributors_from_data(self._podlove_data_for(instance))


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
