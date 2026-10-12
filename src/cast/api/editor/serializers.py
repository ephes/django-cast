from __future__ import annotations

from typing import Any

from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

BODY_SECTIONS = ("overview", "detail")


def markdown_input_field() -> serializers.CharField:
    """Optional Markdown alternative to a body-section block list."""
    return serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)


def validate_body_inputs(attrs: dict[str, Any], *, require_overview: bool) -> dict[str, Any]:
    """Allow either the block list or the Markdown input per body section, never both."""
    errors: dict[str, list[ErrorDetail]] = {}
    for section in BODY_SECTIONS:
        if section in attrs and f"{section}_markdown" in attrs:
            errors[f"{section}_markdown"] = [
                ErrorDetail(f"Send either '{section}' or '{section}_markdown', not both.", code="conflict")
            ]
    if require_overview and "overview" not in attrs and "overview_markdown" not in attrs:
        errors["overview"] = [ErrorDetail("This field is required.", code="required")]
    if errors:
        raise serializers.ValidationError(errors)
    return attrs


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


class PostLookupSerializer(serializers.Serializer):
    parent = serializers.IntegerField(min_value=1)
    slug = serializers.SlugField()


class PostCreateSerializer(serializers.Serializer):
    parent = ParentRefSerializer()
    title = serializers.CharField()
    slug = serializers.SlugField(required=False)
    seo_title = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    search_description = serializers.CharField(required=False, allow_blank=True, default="")
    visible_date = serializers.DateTimeField(required=False)
    cover_image = CoverImageSerializer(required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    categories = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    # ``overview`` or ``overview_markdown`` is required; the block list is canonical.
    overview = serializers.ListField(required=False)
    overview_markdown = markdown_input_field()
    detail = serializers.ListField(required=False)
    detail_markdown = markdown_input_field()
    publish = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return validate_body_inputs(attrs, require_overview=True)


class PostUpdateSerializer(serializers.Serializer):
    base_revision_id = serializers.IntegerField(required=False)
    require_unpublished = serializers.BooleanField(required=False, default=False)
    title = serializers.CharField(required=False)
    slug = serializers.SlugField(required=False)
    seo_title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    search_description = serializers.CharField(required=False, allow_blank=True)
    visible_date = serializers.DateTimeField(required=False)
    cover_image = CoverImageSerializer(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    categories = serializers.ListField(child=serializers.IntegerField(), required=False)
    overview = serializers.ListField(required=False)
    overview_markdown = markdown_input_field()
    detail = serializers.ListField(required=False)
    detail_markdown = markdown_input_field()
    publish = serializers.BooleanField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return validate_body_inputs(attrs, require_overview=False)


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
