from __future__ import annotations

import threading
import time
from datetime import timedelta
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.urls import reverse
from django.utils import timezone

from cast.models import Audio, Blog, Episode, Podcast
from cast.podcast_numbering import (
    _current_publish_state,
    _get_episode_podcast,
    _is_first_publish_candidate,
    _next_available_episode_number,
    assign_episode_number_for_publish,
    episode_type_consumes_number,
)
from tests.factories import EpisodeFactory


def enable_numbering(podcast: Podcast, next_number: int = 1) -> None:
    podcast.automatic_episode_numbering_enabled = True
    podcast.next_episode_number = next_number
    podcast.save(update_fields=["automatic_episode_numbering_enabled", "next_episode_number"])


def make_draft_episode(
    *,
    podcast: Podcast,
    audio,
    body: str,
    slug: str,
    episode_type: str = "",
    episode_number: int | None = None,
    go_live_at=None,
) -> Episode:
    episode = EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title=slug.replace("-", " "),
        slug=slug,
        live=False,
        first_published_at=None,
        episode_type=episode_type,
        episode_number=episode_number,
        go_live_at=go_live_at,
        podcast_audio=audio,
        body=body,
    )
    episode.refresh_from_db()
    return episode


def publish_episode(episode: Episode):
    revision = episode.save_revision()
    revision.publish()
    episode.refresh_from_db()
    revision.refresh_from_db()
    return revision


@pytest.mark.parametrize(
    ("episode_type", "expected"),
    [
        ("", True),
        ("full", True),
        ("trailer", False),
        ("bonus", False),
    ],
)
def test_episode_type_consumes_number(episode_type, expected):
    assert episode_type_consumes_number(episode_type) is expected


@pytest.mark.django_db
def test_get_episode_podcast_handles_non_publishable_shapes(mocker):
    assert _get_episode_podcast(mocker.Mock(get_parent=mocker.Mock(side_effect=ValueError))) is None
    assert _get_episode_podcast(mocker.Mock(get_parent=mocker.Mock(return_value=None))) is None

    parent = SimpleNamespace(specific=Blog(title="Not a podcast"))

    assert _get_episode_podcast(mocker.Mock(get_parent=mocker.Mock(return_value=parent))) is None


@pytest.mark.django_db
def test_is_first_publish_candidate_policy(podcast):
    episode = Episode(live=False, first_published_at=None, episode_number=None, episode_type="")

    assert _is_first_publish_candidate(episode, podcast) is False

    podcast.automatic_episode_numbering_enabled = True
    assert _is_first_publish_candidate(episode, podcast) is True

    episode.live = True
    assert _is_first_publish_candidate(episode, podcast) is False
    episode.live = False
    episode.first_published_at = timezone.now()
    assert _is_first_publish_candidate(episode, podcast) is False
    episode.first_published_at = None
    episode.go_live_at = timezone.now() + timedelta(days=1)
    assert _is_first_publish_candidate(episode, podcast) is False
    episode.go_live_at = None
    episode.episode_number = 7
    assert _is_first_publish_candidate(episode, podcast) is False
    episode.episode_number = None
    episode.episode_type = Episode.EpisodeType.TRAILER
    assert _is_first_publish_candidate(episode, podcast) is False


@pytest.mark.django_db
def test_default_disabled_numbering_does_nothing(podcast, audio, body):
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="disabled-numbering")

    revision = publish_episode(episode)

    assert episode.live is True
    assert episode.episode_number is None
    assert revision.content["episode_number"] is None
    podcast.refresh_from_db()
    assert podcast.automatic_episode_numbering_enabled is False
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_enabled_podcast_assigns_first_blank_full_episode_and_persists_revision(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(
        podcast=podcast,
        audio=audio,
        body=body,
        slug="numbered-full",
        episode_type=Episode.EpisodeType.FULL,
    )
    original_uuid = episode.uuid
    original_slug = episode.slug

    revision = publish_episode(episode)

    assert episode.episode_number == 1
    assert episode.uuid == original_uuid
    assert episode.slug == original_slug
    assert revision.content["episode_number"] == 1
    assert episode.live_revision.as_object().episode_number == 1
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 2


@pytest.mark.django_db
def test_automatic_numbering_does_not_change_feed_guid(client, podcast, audio, body, use_dummy_cache_backend):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="numbered-feed-guid")
    original_uuid = episode.uuid
    publish_episode(episode)
    feed_url = reverse("cast:podcast_feed_rss", kwargs={"slug": podcast.slug, "audio_format": "m4a"})

    response = client.get(feed_url)

    root = ElementTree.fromstring(response.content.decode("utf-8"))
    guid = root.find("./channel/item/guid")
    assert guid is not None
    assert guid.text == str(original_uuid)
    assert guid.attrib == {"isPermaLink": "false"}


@pytest.mark.django_db
def test_blank_episode_type_consumes_number_as_full(podcast, audio, body):
    enable_numbering(podcast, next_number=5)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="blank-type")

    publish_episode(episode)

    assert episode.episode_number == 5
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 6


@pytest.mark.django_db
@pytest.mark.parametrize("episode_type", [Episode.EpisodeType.TRAILER, Episode.EpisodeType.BONUS])
def test_trailer_and_bonus_do_not_consume_numbers(podcast, audio, body, episode_type):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug=f"not-full-{episode_type}")
    episode.episode_type = episode_type
    episode.save(update_fields=["episode_type"])

    publish_episode(episode)

    assert episode.episode_number is None
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_draft_save_does_not_consume_number(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="draft-only")

    revision = episode.save_revision()

    assert revision.content["episode_number"] is None
    episode.refresh_from_db()
    assert episode.episode_number is None
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_future_scheduled_publish_does_not_consume_at_approval_time(podcast, audio, body):
    enable_numbering(podcast)
    future = timezone.now() + timedelta(days=1)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="future-scheduled", go_live_at=future)

    revision = publish_episode(episode)

    assert episode.live is False
    assert episode.episode_number is None
    assert revision.content["episode_number"] is None
    assert revision.approved_go_live_at == future
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_scheduled_publish_assigns_when_episode_goes_live(podcast, audio, body):
    enable_numbering(podcast)
    due = timezone.now() - timedelta(minutes=1)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="due-scheduled", go_live_at=due)
    revision = episode.save_revision(approved_go_live_at=due)

    call_command("publish_scheduled", verbosity=0)

    episode.refresh_from_db()
    revision.refresh_from_db()
    assert episode.live is True
    assert episode.episode_number == 1
    assert revision.content["episode_number"] == 1
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 2


@pytest.mark.django_db
def test_existing_manual_number_is_not_changed_on_publish_or_republish(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(
        podcast=podcast,
        audio=audio,
        body=body,
        slug="manual-number",
        episode_number=99,
    )

    first_revision = publish_episode(episode)
    second_revision = publish_episode(episode)

    assert episode.episode_number == 99
    assert first_revision.content["episode_number"] == 99
    assert second_revision.content["episode_number"] == 99
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_automatic_assignment_skips_existing_manual_numbers_under_same_podcast(podcast, audio, body):
    enable_numbering(podcast)
    EpisodeFactory(
        owner=podcast.owner,
        parent=podcast,
        title="Manual one",
        slug="manual-one",
        episode_number=1,
        podcast_audio=audio,
        body=body,
    )
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="after-manual-one")

    assert _next_available_episode_number(podcast, episode) == 2
    publish_episode(episode)

    assert episode.episode_number == 2
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 3


@pytest.mark.django_db
def test_full_episode_changed_to_trailer_keeps_assigned_number(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="full-then-trailer")
    publish_episode(episode)
    episode.episode_type = Episode.EpisodeType.TRAILER

    revision = publish_episode(episode)

    assert episode.episode_number == 1
    assert revision.content["episode_number"] == 1
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 2


@pytest.mark.django_db
def test_trailer_changed_to_full_after_publish_does_not_get_number(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(
        podcast=podcast,
        audio=audio,
        body=body,
        slug="trailer-then-full",
        episode_type=Episode.EpisodeType.TRAILER,
    )
    publish_episode(episode)
    episode.episode_type = Episode.EpisodeType.FULL

    publish_episode(episode)

    assert episode.episode_number is None
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_editing_after_automatic_publish_keeps_number_from_revision(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="edit-after-publish")
    assigned_revision = publish_episode(episode)

    assigned_revision.publish()
    episode.refresh_from_db()
    assert episode.episode_number == 1

    episode.title = "Edited after publish"
    edited_revision = publish_episode(episode)

    assert episode.episode_number == 1
    assert edited_revision.content["episode_number"] == 1
    assert episode.live_revision.as_object().episode_number == 1


@pytest.mark.django_db
def test_service_without_revision_assigns_object_and_counter(podcast, audio, body):
    enable_numbering(podcast, next_number=4)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="service-without-revision")

    assigned = assign_episode_number_for_publish(episode)

    assert assigned == 4
    assert episode.episode_number == 4
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 5


@pytest.mark.django_db
def test_service_returns_none_for_parentless_episode():
    episode = Episode(title="Parentless", slug="parentless", live=False)

    assert assign_episode_number_for_publish(episode) is None


@pytest.mark.django_db
def test_current_publish_state_handles_missing_episode_row():
    assert _current_publish_state(Episode(pk=999999, live=False)) == (False, None, None)


@pytest.mark.django_db
def test_service_returns_none_when_policy_changes_after_lock(podcast, mocker):
    enable_numbering(podcast)
    episode = Episode(live=False, first_published_at=None, episode_number=None, episode_type="")
    mocker.patch("cast.podcast_numbering._get_episode_podcast", return_value=podcast)
    is_first_publish_candidate = mocker.patch("cast.podcast_numbering._is_first_publish_candidate", return_value=False)

    assert assign_episode_number_for_publish(episode) is None
    is_first_publish_candidate.assert_called_once()


@pytest.mark.django_db
def test_stale_first_publish_preserves_number_assigned_by_earlier_publish(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="stale-first-publish")
    stale_episode = Episode.objects.get(pk=episode.pk)
    revision = stale_episode.save_revision()
    publish_episode(episode)

    assigned = assign_episode_number_for_publish(stale_episode, revision)

    assert assigned == 1
    assert stale_episode.episode_number == 1
    revision.refresh_from_db()
    assert revision.content["episode_number"] == 1
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 2


@pytest.mark.django_db
def test_stale_blank_trailer_revision_preserves_existing_number_on_publish(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="stale-trailer-with-number")
    stale_episode = Episode.objects.get(pk=episode.pk)
    stale_episode.episode_type = Episode.EpisodeType.TRAILER
    stale_revision = stale_episode.save_revision()
    publish_episode(episode)

    stale_revision.publish()

    episode.refresh_from_db()
    stale_revision.refresh_from_db()
    assert episode.episode_type == Episode.EpisodeType.TRAILER
    assert episode.episode_number == 1
    assert stale_revision.content["episode_number"] == 1
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 2


@pytest.mark.django_db
def test_reverted_blank_revision_preserves_existing_number_on_publish(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="revert-preserves-number")
    blank_revision = episode.save_revision()
    publish_episode(episode)
    reverted_episode = blank_revision.as_object()
    reverted_revision = reverted_episode.save_revision(previous_revision=blank_revision)

    reverted_revision.publish(previous_revision=blank_revision)

    episode.refresh_from_db()
    reverted_revision.refresh_from_db()
    assert episode.episode_number == 1
    assert reverted_revision.content["episode_number"] == 1
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 2


@pytest.mark.django_db
def test_new_blank_revision_can_clear_existing_episode_number(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="clear-existing-number")
    publish_episode(episode)
    episode.episode_number = None
    clear_revision = episode.save_revision()

    clear_revision.publish()

    episode.refresh_from_db()
    clear_revision.refresh_from_db()
    assert episode.episode_number is None
    assert clear_revision.content["episode_number"] is None
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 2


@pytest.mark.django_db
def test_stale_blank_revision_preserves_existing_manual_number_when_numbering_disabled(podcast, audio, body):
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="disabled-stale-manual")
    stale_revision = episode.save_revision()
    episode.episode_number = 88
    publish_episode(episode)

    stale_revision.publish()

    episode.refresh_from_db()
    stale_revision.refresh_from_db()
    assert episode.episode_number == 88
    assert stale_revision.content["episode_number"] == 88
    podcast.refresh_from_db()
    assert podcast.automatic_episode_numbering_enabled is False
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_stale_first_publish_does_not_assign_when_episode_was_published_without_number(podcast, audio, body):
    enable_numbering(podcast)
    episode = make_draft_episode(
        podcast=podcast,
        audio=audio,
        body=body,
        slug="stale-trailer-publish",
        episode_type=Episode.EpisodeType.TRAILER,
    )
    stale_episode = Episode.objects.get(pk=episode.pk)
    revision = stale_episode.save_revision()
    publish_episode(episode)

    assigned = assign_episode_number_for_publish(stale_episode, revision)

    assert assigned is None
    assert stale_episode.episode_number is None
    revision.refresh_from_db()
    assert revision.content["episode_number"] is None
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_stale_first_publish_does_not_assign_after_disabled_publish_without_number(podcast, audio, body):
    episode = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="disabled-then-stale")
    stale_episode = Episode.objects.get(pk=episode.pk)
    revision = stale_episode.save_revision()
    publish_episode(episode)
    enable_numbering(podcast)

    assigned = assign_episode_number_for_publish(stale_episode, revision)

    assert assigned is None
    assert stale_episode.episode_number is None
    revision.refresh_from_db()
    assert revision.content["episode_number"] is None
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 1


@pytest.mark.django_db
def test_serialized_stale_publish_attempts_do_not_assign_duplicate_numbers(podcast, audio, body):
    enable_numbering(podcast)
    first = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="concurrent-one")
    second = make_draft_episode(podcast=podcast, audio=audio, body=body, slug="concurrent-two")
    first_revision = first.save_revision()
    second_revision = second.save_revision()
    first_attempt = first_revision.as_object()
    second_attempt = second_revision.as_object()

    assign_episode_number_for_publish(first_attempt, first_revision)
    first_attempt.save()
    assign_episode_number_for_publish(second_attempt, second_revision)
    second_attempt.save()

    numbers = list(Episode.objects.filter(pk__in=[first.pk, second.pk]).values_list("episode_number", flat=True))
    assert sorted(numbers) == [1, 2]
    podcast.refresh_from_db()
    assert podcast.next_episode_number == 3


@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL row-lock semantics")
@pytest.mark.parametrize("independent_podcasts", [False, True])
def test_postgres_first_publications_serialize_per_podcast(pg_editor_actors, monkeypatch, independent_podcasts):
    """Hold a real allocation mid-transaction and observe the competing backend."""
    from wagtail.models import Revision

    from cast import podcast_numbering
    from tests.factories import PodcastFactory

    user, blog = pg_editor_actors
    first_podcast = PodcastFactory(parent=blog.get_parent(), owner=user, slug="first-show")
    enable_numbering(first_podcast, next_number=7)
    second_podcast = first_podcast
    if independent_podcasts:
        second_podcast = PodcastFactory(parent=blog.get_parent(), owner=user, slug="second-show")
        enable_numbering(second_podcast, next_number=7)
    audio = Audio.objects.create(user=user, title="Synthetic audio")
    episodes = [
        make_draft_episode(podcast=show, audio=audio, body=[], slug=f"allocation-{index}")
        for index, show in enumerate((first_podcast, second_podcast))
    ]
    revisions = [episode.save_revision() for episode in episodes]
    first_allocating = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_finished = threading.Event()
    errors = []
    backend_pids = {}
    original_next_number = podcast_numbering._next_available_episode_number

    def pause_first(locked_podcast, episode):
        number = original_next_number(locked_podcast, episode)
        if episode.pk == episodes[0].pk:
            first_allocating.set()
            assert release_first.wait(10), "First allocation was never released"
        return number

    monkeypatch.setattr(podcast_numbering, "_next_available_episode_number", pause_first)

    def publish(index):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '15s'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_pids[index] = cursor.fetchone()[0]
            if index == 1:
                second_started.set()
            Revision.objects.get(pk=revisions[index].pk).publish()
            if index == 1:
                second_finished.set()
        except Exception as error:
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=publish, args=(index,)) for index in range(2)]
    threads[0].start()
    try:
        assert first_allocating.wait(10), errors
        threads[1].start()
        assert second_started.wait(10), errors
        assert len(set(backend_pids.values())) == 2
        if independent_podcasts:
            assert second_finished.wait(10), errors
        else:
            deadline = time.monotonic() + 5
            with connection.cursor() as cursor:
                while time.monotonic() < deadline:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [backend_pids[1]])
                    if backend_pids[0] in cursor.fetchone()[0]:
                        break
                    assert not second_finished.is_set(), "Second publication bypassed the podcast counter lock"
                    assert not errors, errors
                    time.sleep(0.01)
                else:
                    pytest.fail("Second publication never waited for the first allocation")
    finally:
        release_first.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=20)
        assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert second_finished.is_set()
    for episode, revision, expected in zip(episodes, revisions, (7, 7 if independent_podcasts else 8), strict=True):
        episode.refresh_from_db()
        revision.refresh_from_db()
        assert episode.live
        assert episode.live_revision_id == revision.pk
        assert episode.episode_number == revision.content["episode_number"] == expected
    for show in (first_podcast, second_podcast):
        show.refresh_from_db()
        assert show.next_episode_number == (8 if independent_podcasts else 9)
    # Republishing either revision must preserve its number and the counter.
    for episode, revision, expected in zip(episodes, revisions, (7, 7 if independent_podcasts else 8), strict=True):
        revision.publish()
        episode.refresh_from_db()
        revision.refresh_from_db()
        assert episode.episode_number == revision.content["episode_number"] == expected
    for show in (first_podcast, second_podcast):
        show.refresh_from_db()
        assert show.next_episode_number == (8 if independent_podcasts else 9)
