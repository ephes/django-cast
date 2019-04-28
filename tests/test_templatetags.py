import os
import pytest

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
