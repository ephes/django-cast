from datetime import time
from io import BytesIO

import pytest
from django.core.cache import caches
from django.core.files.base import ContentFile
from PIL import Image as PillowImage
from wagtail.images.models import Image

from cast.models import Audio, ChapterMark, Contributor, Episode, EpisodeContributor
from cast.models.repository import PostQuerySnapshot
from tests.factories import EpisodeFactory


@pytest.mark.django_db
@pytest.mark.parametrize("count", [1, 20])
def test_chapter_readers_reuse_prefetch(user, count, django_assert_num_queries):
    audios = []
    for index in range(count):
        audio = Audio.objects.create(user=user, title=f"Synthetic {index}")
        ChapterMark.objects.create(audio=audio, start=time(0, 2), title="Later", link="https://example.com/later")
        ChapterMark.objects.create(
            audio=audio, start=time(0, 1, 0, 123000), title="First", image="https://example.com/a.png"
        )
        audios.append(audio.pk)
    loaded = list(Audio.objects.filter(pk__in=audios).prefetch_related("chaptermarks").order_by("pk"))
    with django_assert_num_queries(0):
        for audio in loaded:
            assert audio.chapters == [
                {"start": "00:01:00.123", "title": "First", "href": None, "image": "https://example.com/a.png"},
                {"start": "00:02:00", "title": "Later", "href": "https://example.com/later", "image": None},
            ]
            assert audio.chapters_as_text == "00:01:00.123000 First\n00:02:00 Later"
    fresh = Audio.objects.get(pk=audios[0])
    with django_assert_num_queries(1):
        assert fresh.chapters == loaded[0].chapters
    with django_assert_num_queries(1):
        assert fresh.chapters_as_text == loaded[0].chapters_as_text


@pytest.mark.django_db
@pytest.mark.parametrize("count", [1, 20])
def test_snapshot_avatar_rendition_budget(podcast, rf, count, django_assert_num_queries):
    episodes = []
    urls = {}
    for index in range(count):
        data = BytesIO()
        PillowImage.new("RGB", (100, 100), color=(index, 20, 30)).save(data, format="PNG")
        image = Image.objects.create(
            title=f"Avatar {index}", file=ContentFile(data.getvalue(), name=f"avatar-{index}.png")
        )
        contributor = Contributor.objects.create(display_name=f"Person {index}", slug=f"person-{index}", avatar=image)
        urls[contributor.pk] = image.get_rendition(Contributor.AVATAR_RENDITION_FILTER).url
        episode = EpisodeFactory(
            parent=podcast,
            owner=podcast.owner,
            slug=f"episode-{index}",
            title=f"Episode {index}",
            body=[],
            podcast_audio=None,
        )
        EpisodeContributor.objects.create(episode=episode, contributor=contributor)
        episodes.append(episode.pk)
    other = EpisodeFactory(
        parent=podcast, owner=podcast.owner, slug="shared", title="Shared", body=[], podcast_audio=None
    )
    EpisodeContributor.objects.create(episode=other, contributor=contributor)
    avatarless = Contributor.objects.create(display_name="No avatar", slug="no-avatar")
    urls[avatarless.pk] = ""
    EpisodeContributor.objects.create(episode=other, contributor=avatarless)
    episodes.append(other.pk)
    for cache in caches.all():
        cache.clear()
    site = podcast.get_site()
    with django_assert_num_queries(8):
        snapshot = PostQuerySnapshot.create_from_post_queryset(
            request=rf.get("/"), site=site, queryset=Episode.objects.filter(pk__in=episodes).order_by("pk")
        )
    with django_assert_num_queries(0):
        for episode in snapshot.post_by_id.values():
            for assignment in episode.visible_contributor_assignments:
                assert assignment.get_avatar_rendition_url() == urls[assignment.contributor_id]


@pytest.mark.django_db
def test_snapshot_generates_missing_avatar_derivative(podcast, rf):
    data = BytesIO()
    PillowImage.new("RGB", (100, 100), color="blue").save(data, format="PNG")
    image = Image.objects.create(title="Synthetic avatar", file=ContentFile(data.getvalue(), name="missing.png"))
    contributor = Contributor.objects.create(display_name="Synthetic", slug="synthetic", avatar=image)
    episode = EpisodeFactory(parent=podcast, owner=podcast.owner, title="Synthetic", body=[], podcast_audio=None)
    EpisodeContributor.objects.create(episode=episode, contributor=contributor)
    assert not image.renditions.exists()
    snapshot = PostQuerySnapshot.create_from_post_queryset(
        request=rf.get("/"), site=podcast.get_site(), queryset=Episode.objects.filter(pk=episode.pk)
    )
    assignment = snapshot.post_by_id[episode.pk].visible_contributor_assignments[0]
    assert assignment.get_avatar_rendition_url() == image.renditions.get().url
