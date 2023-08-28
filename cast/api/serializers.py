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
