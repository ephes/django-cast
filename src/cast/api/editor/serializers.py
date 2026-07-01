from __future__ import annotations

from rest_framework import serializers


class ParentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    type = serializers.CharField(read_only=True)
    api_url = serializers.CharField(read_only=True)


class ParentRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()


class CoverImageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    alt_text = serializers.CharField(required=False, allow_blank=True, default="")


class PostCreateSerializer(serializers.Serializer):
    parent = ParentRefSerializer()
    title = serializers.CharField()
    slug = serializers.SlugField(required=False)
    visible_date = serializers.DateTimeField(required=False)
    cover_image = CoverImageSerializer(required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    categories = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    overview = serializers.ListField()  # required: the structured overview block list
    detail = serializers.ListField(required=False)
    publish = serializers.BooleanField(required=False, default=False)


class PostUpdateSerializer(serializers.Serializer):
    base_revision_id = serializers.IntegerField()
    title = serializers.CharField(required=False)
    slug = serializers.SlugField(required=False)
    visible_date = serializers.DateTimeField(required=False)
    cover_image = CoverImageSerializer(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    categories = serializers.ListField(child=serializers.IntegerField(), required=False)
    overview = serializers.ListField(required=False)
    detail = serializers.ListField(required=False)
    publish = serializers.BooleanField(required=False)


class MediaRefSerializer(serializers.Serializer):
    """An ``{"id": <object id>}`` reference to a single media object."""

    id = serializers.IntegerField()


def episode_metadata_fields() -> dict:
    """The episode-specific serializer fields, sourced from the model to avoid choice drift."""
    from ...models import Episode

    return {
        "podcast_audio": MediaRefSerializer(required=False, allow_null=True),
        "episode_number": serializers.IntegerField(required=False, allow_null=True, min_value=1),
        "episode_type": serializers.ChoiceField(choices=Episode.EpisodeType.choices, required=False, allow_blank=True),
        "season": MediaRefSerializer(required=False, allow_null=True),
        "keywords": serializers.CharField(required=False, allow_blank=True),
        "explicit": serializers.ChoiceField(choices=Episode.EXPLICIT_CHOICES, required=False),
        "block": serializers.BooleanField(required=False),
    }


class EpisodeCreateSerializer(PostCreateSerializer):
    """Create payload for a draft ``Episode``: the post fields plus episode-specific metadata."""

    def get_fields(self) -> dict:
        return {**super().get_fields(), **episode_metadata_fields()}


class EpisodeUpdateSerializer(PostUpdateSerializer):
    """Update payload for a draft ``Episode``: the post fields plus episode-specific metadata."""

    def get_fields(self) -> dict:
        return {**super().get_fields(), **episode_metadata_fields()}
