from pathlib import Path

import pytest
from wagtail.images import get_image_model
from wagtail.models import Page

from cast import devdata
from cast.models import Audio, Episode, Gallery, Video


def test_default_media_fixtures_do_not_need_the_checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(devdata, "__file__", str(tmp_path / "installed" / "cast" / "devdata.py"))

    for upload in (devdata.create_m4a_file(), devdata.create_mp4_file(fixture_name="test_video.mp4")):
        assert upload.read(16)[4:8] == b"ftyp"


def test_media_fixtures_accept_an_explicit_directory(tmp_path):
    for filename in ("test.m4a", "alternate.mp4"):
        (tmp_path / filename).write_bytes(filename.encode())
    assert devdata.create_m4a_file(fixture_dir=tmp_path).read() == b"test.m4a"
    assert devdata.create_mp4_file(fixture_dir=tmp_path, fixture_name="alternate.mp4").read() == b"alternate.mp4"


@pytest.mark.parametrize(
    ("number_of_posts", "media_numbers", "message"),
    [
        (1, {"audios": 0, "videos": 1, "images": 1, "galleries": 1}, "Podcast episodes require at least one audio"),
        (-1, {"audios": 1}, "number_of_posts must be a nonnegative integer"),
        (1, {"audios": -1}, "audios must be a nonnegative integer"),
        (1, {"audios": 1, "videos": True}, "videos must be a nonnegative integer"),
        (1, {"audios": 1, "images": 0.5}, "images must be a nonnegative integer"),
        (1, {"audios": 1, "galleries": -1}, "galleries must be a nonnegative integer"),
        (1, {"audios": 1, "images_in_galleries": -1}, "images_in_galleries must be a nonnegative integer"),
    ],
)
def test_invalid_podcast_seed_does_not_create_pages_or_media(site, settings, number_of_posts, media_numbers, message):
    models = (Page, Audio, Video, Gallery, get_image_model())
    counts = [model.objects.count() for model in models]
    files_before = set(Path(settings.MEDIA_ROOT).rglob("*"))

    with pytest.raises(ValueError, match=message):
        devdata.generate_blog_with_media(number_of_posts=number_of_posts, media_numbers=media_numbers, podcast=True)

    assert [model.objects.count() for model in models] == counts
    assert set(Path(settings.MEDIA_ROOT).rglob("*")) == files_before


@pytest.mark.parametrize("number_of_posts", [0, 1])
def test_seed_with_zero_videos_does_not_read_mp4(site, monkeypatch, number_of_posts):
    def unexpected_fixture_read():
        pytest.fail("Requested an MP4 fixture with videos=0")

    monkeypatch.setattr(devdata, "create_mp4_file", unexpected_fixture_read)
    podcast = devdata.generate_blog_with_media(
        number_of_posts=number_of_posts, media_numbers={"audios": number_of_posts, "videos": 0}, podcast=True
    )

    episodes = Episode.objects.child_of(podcast)
    assert episodes.count() == number_of_posts
    if number_of_posts:
        assert episodes.get().podcast_audio.m4a
