import pytest

from cast.templatetags.cast_extras import audio as audio_tag
from cast.templatetags.cast_extras import gallery as gallery_tag
from cast.templatetags.cast_extras import video as video_tag


class TestVideoTag:
    @pytest.mark.django_db
    def test_video_template_tag(self, video):
        context = {"video": {video.pk: video}}
        tag = video_tag(context, video.pk)
        assert "svg" in tag
        assert "test.png" not in tag
        assert "video/mp4" in tag

    @pytest.mark.django_db
    def test_video_template_tag_with_poster(self, video_with_poster):
        video = video_with_poster
        context = {"video": {video.pk: video}}
        tag = video_tag(context, video.pk)
        assert "svg" not in tag
        assert "test.png" in tag
        assert "video/mp4" in tag


class TestAudioTag:
    @pytest.mark.django_db
    def test_audio_template_tag(self, audio):
        context = {"audio": {audio.pk: audio}}
        tag = audio_tag(context, audio.pk)
        assert f"audio_{audio.pk}" in tag


class TestGalleryTag:
    @pytest.mark.django_db
    def test_gallery_template_tag_with_javascript(self, post, gallery):
        context = {"gallery": {gallery.pk: gallery}, "post": post}
        tag = gallery_tag(context, gallery.pk)
        assert "galleryModal" in tag

    @pytest.mark.django_db
    def test_gallery_template_tag_without_javascript(self, post, gallery):
        context = {"gallery": {gallery.pk: gallery}, "post": post, "javascript": False}
        tag = gallery_tag(context, gallery.pk)
        assert "Modal" not in tag
        assert "srcset" in tag
