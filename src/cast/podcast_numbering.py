from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from wagtail.models import Revision

    from cast.models import Episode, Podcast

_PUBLISH_REVISION_PARAMETER_NAMES = ("revision", "object", "user", "changed", "log_action", "previous_revision")
logger = logging.getLogger(__name__)


def episode_type_consumes_number(episode_type: str) -> bool:
    return episode_type in {"", "full"}


def _get_episode_podcast(episode: "Episode") -> "Podcast | None":
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


def _is_first_publish_candidate(episode: "Episode", podcast: "Podcast") -> bool:
    if not podcast.automatic_episode_numbering_enabled:
        return False
    if episode.live or episode.first_published_at is not None:
        return False
    if episode.go_live_at is not None and episode.go_live_at > timezone.now():
        return False
    return episode.episode_number is None and episode_type_consumes_number(episode.episode_type)


def _used_episode_numbers(podcast: "Podcast", episode: "Episode") -> set[int]:
    from cast.models import Episode

    return set(
        Episode.objects.descendant_of(podcast)
        .exclude(pk=episode.pk)
        .filter(episode_number__isnull=False)
        .values_list("episode_number", flat=True)
    )


def _next_available_episode_number(podcast: "Podcast", episode: "Episode") -> int:
    episode_number = podcast.next_episode_number
    used_numbers = _used_episode_numbers(podcast, episode)
    while episode_number in used_numbers:
        episode_number += 1
    return episode_number


def _update_revision_episode_number(revision: "Revision | None", episode_number: int) -> None:
    if revision is None:
        return
    revision.content["episode_number"] = episode_number
    revision.save(update_fields=["content"])


def _current_publish_state(episode: "Episode") -> tuple[bool, int | None, int | None]:
    from cast.models import Episode

    current = (
        Episode.objects.filter(pk=episode.pk)
        .values("episode_number", "live", "first_published_at", "live_revision_id")
        .first()
    )
    if current is None:
        return False, None, None
    if current["live"] or current["first_published_at"] is not None:
        return True, current["episode_number"], current["live_revision_id"]
    return False, None, None


def _should_preserve_current_episode_number(
    episode: "Episode",
    revision: "Revision | None",
    previous_revision: "Revision | None",
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
    episode: "Episode",
    revision: "Revision | None" = None,
    previous_revision: "Revision | None" = None,
) -> int | None:
    podcast = _get_episode_podcast(episode)
    if podcast is None:
        return None

    with transaction.atomic():
        from cast.models import Podcast

        locked_podcast = Podcast.objects.select_for_update().get(pk=podcast.pk)

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


def _validate_publish_revision_api(publish_revision: Any) -> None:
    if publish_revision is None:
        raise RuntimeError("Wagtail PublishRevisionAction._publish_revision is not available")
    parameters = inspect.signature(publish_revision).parameters
    missing_parameters = {"revision", "object", "previous_revision"} - set(parameters)
    if missing_parameters:
        missing = ", ".join(sorted(missing_parameters))
        raise RuntimeError(f"Unsupported Wagtail PublishRevisionAction._publish_revision API; missing {missing}")
    positional_parameters = tuple(name for name in parameters if name in _PUBLISH_REVISION_PARAMETER_NAMES)
    if positional_parameters != _PUBLISH_REVISION_PARAMETER_NAMES:
        raise RuntimeError("Unsupported Wagtail PublishRevisionAction._publish_revision positional parameter order")


def _publish_revision_and_object(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple["Revision", Any, "Revision | None"]:
    arguments = dict(zip(_PUBLISH_REVISION_PARAMETER_NAMES, args, strict=False))
    arguments.update(kwargs)
    return arguments["revision"], arguments["object"], arguments.get("previous_revision")


def install_episode_numbering_publish_hook() -> None:
    from wagtail.actions.publish_revision import PublishRevisionAction

    original = getattr(PublishRevisionAction, "_publish_revision", None)
    if getattr(original, "_cast_episode_numbering_hook", False):
        return
    try:
        # Wagtail 7.4 has no public pre-save publish hook that can update both
        # the revision content and live object, so this private hook is guarded.
        _validate_publish_revision_api(original)
    except RuntimeError as error:
        logger.warning("Automatic episode numbering publish hook was not installed: %s", error)
        return
    assert original is not None

    def publish_revision_with_episode_numbering(
        self: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        from cast.models import Episode

        revision, object_to_publish, previous_revision = _publish_revision_and_object(args, kwargs)
        if isinstance(object_to_publish, Episode):
            with transaction.atomic():
                assign_episode_number_for_publish(object_to_publish, revision, previous_revision=previous_revision)
                return original(self, *args, **kwargs)
        return original(self, *args, **kwargs)

    setattr(publish_revision_with_episode_numbering, "_cast_episode_numbering_hook", True)
    setattr(publish_revision_with_episode_numbering, "_cast_episode_numbering_original", original)
    PublishRevisionAction._publish_revision = publish_revision_with_episode_numbering  # type: ignore[method-assign]
