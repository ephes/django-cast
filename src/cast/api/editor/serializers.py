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
