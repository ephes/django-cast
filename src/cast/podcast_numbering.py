from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import router, transaction
from django.utils import timezone

if TYPE_CHECKING:
    from wagtail.models import Revision

    from cast.models import Episode, Podcast


def episode_type_consumes_number(episode_type: str) -> bool:
    return episode_type in {"", "full"}


def _get_episode_podcast(episode: Episode) -> Podcast | None:
    from cast.models import Podcast

    try:
        parent = episode.get_parent()
    except (ObjectDoesNotExist, ValueError):
        return None
    if parent is None:
        return None
    podcast = parent.specific
    if isinstance(podcast, Podcast):
        return podcast
    return None


def _is_first_publish_candidate(episode: Episode, podcast: Podcast) -> bool:
    if not podcast.automatic_episode_numbering_enabled:
        return False
    if episode.live or episode.first_published_at is not None:
        return False
    if episode.go_live_at is not None and episode.go_live_at > timezone.now():
        return False
    return episode.episode_number is None and episode_type_consumes_number(episode.episode_type)


def _used_episode_numbers(podcast: Podcast, episode: Episode) -> Iterator[int]:
    from cast.models import Episode

    return (
        Episode.objects.using(episode._state.db)
        .descendant_of(podcast)
        .exclude(pk=episode.pk)
        .filter(episode_number__gte=podcast.next_episode_number)
        .order_by("episode_number")
        .values_list("episode_number", flat=True)
        .iterator(chunk_size=1000)
    )


def _next_available_episode_number(podcast: Podcast, episode: Episode) -> int:
    episode_number = podcast.next_episode_number
    for used_number in _used_episode_numbers(podcast, episode):
        if used_number > episode_number:
            break
        if used_number == episode_number:
            episode_number += 1
    return episode_number


def _update_revision_episode_number(revision: Revision | None, episode_number: int) -> None:
    if revision is None:
        return
    revision.content["episode_number"] = episode_number
    revision.save(update_fields=["content"])


def _current_publish_state(episode: Episode) -> tuple[bool, int | None, int | None]:
    from cast.models import Episode

    current = (
        Episode.objects.using(episode._state.db)
        .filter(pk=episode.pk)
        .values("episode_number", "live", "first_published_at", "live_revision_id")
        .first()
    )
    if current is None:
        return False, None, None
    if current["live"] or current["first_published_at"] is not None:
        return True, current["episode_number"], current["live_revision_id"]
    return False, None, None


def _should_preserve_current_episode_number(
    episode: Episode,
    revision: Revision | None,
    previous_revision: Revision | None,
    already_published: bool,
    current_episode_number: int | None,
    live_revision_id: int | None,
) -> bool:
    if episode.episode_number is not None or not already_published or current_episode_number is None:
        return False
    if revision is None or live_revision_id is None or previous_revision is not None:
        return True
    return revision.pk is not None and revision.pk <= live_revision_id


def assign_episode_number_for_publish(
    episode: Episode,
    revision: Revision | None = None,
    previous_revision: Revision | None = None,
) -> int | None:
    using = episode._state.db or router.db_for_write(type(episode), instance=episode)
    if any(item is not None and item._state.db != using for item in (revision, previous_revision)):
        raise ValidationError("The revision belongs to a different database.")
    podcast = _get_episode_podcast(episode)
    if podcast is None:
        return None

    with transaction.atomic(using=using):
        from cast.models import Podcast

        locked_podcast = Podcast.objects.using(using).select_for_update().get(pk=podcast.pk)

        already_published, current_episode_number, live_revision_id = _current_publish_state(episode)
        if _should_preserve_current_episode_number(
            episode,
            revision,
            previous_revision,
            already_published,
            current_episode_number,
            live_revision_id,
        ):
            assert current_episode_number is not None
            episode.episode_number = current_episode_number
            _update_revision_episode_number(revision, current_episode_number)
            return current_episode_number
        if already_published:
            return None

        if not _is_first_publish_candidate(episode, locked_podcast):
            return None

        episode_number = _next_available_episode_number(locked_podcast, episode)
        episode.episode_number = episode_number
        _update_revision_episode_number(revision, episode_number)
        locked_podcast.next_episode_number = episode_number + 1
        locked_podcast.save(update_fields=["next_episode_number"])
        return episode_number
