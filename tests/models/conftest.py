import pytest

from cast.models import Video


@pytest.fixture()
def video_with_poster(user, minimal_mp4, image_1px):
    video = Video(user=user, original=minimal_mp4, poster=image_1px)
    video.save()
    return video
