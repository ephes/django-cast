import logging

from rest_framework import serializers

from ..models import Image, Video, Gallery, Audio

logger = logging.getLogger(__name__)


class ImageSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="cast:api:image_detail")
    srcset = serializers.ReadOnlyField()
    thumbnail_src = serializers.ReadOnlyField()
    full_src = serializers.ReadOnlyField()

    class Meta:
        model = Image
        fields = ("id", "url", "original", "srcset", "thumbnail_src", "full_src")


class VideoSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="cast:api:video_detail")
    poster = serializers.ImageField(read_only=True, allow_empty_file=True)
    poster_thumbnail = serializers.ImageField(read_only=True, allow_empty_file=True)

    class Meta:
        model = Video
        fields = ("id", "url", "original", "poster", "poster_thumbnail")


class AudioSerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="cast:api:audio_detail")
    podlove = serializers.HyperlinkedIdentityField(
        view_name="cast:api:audio_podlove_detail"
    )

    class Meta:
        model = Audio
        fields = ("id", "name", "file_formats", "url", "podlove", "mp3")


class AudioPodloveSerializer(serializers.HyperlinkedModelSerializer):
    audio = serializers.ListField()
    chapters = serializers.ListField()
    duration = serializers.CharField(source="duration_str")

    class Meta:
        model = Audio
        fields = ("title", "subtitle", "audio", "duration", "chapters")


class GallerySerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="cast:api:gallery_detail")
    images = serializers.PrimaryKeyRelatedField(many=True, queryset=Image.objects.all())

    def create(self, validated_data):
        user = self.context["request"].user
        gallery = Gallery.objects.create(user=user)
        for image in validated_data["images"]:
            gallery.images.add(image)
        return gallery

    class Meta:
        model = Gallery
        fields = ("id", "url", "images")
