"""Access control for the public audio and transcript object endpoints.

Several endpoints serve ``Audio`` / ``Transcript`` content addressed by a raw
object id. Content may only be served when the object is reachable through a
live episode/post whose Wagtail view restrictions the request satisfies (the
public path), or when the requester may edit a referencing page (the
editor/preview path). Anything else raises ``Http404`` so object existence is
never leaked.

The decision helpers live here (rather than in ``transcript_sanitization``) to
keep access control separate from the speaker-label sanitization that runs once
access has been granted.
"""

from __future__ import annotations

from typing import Any

from django.http import Http404


def page_is_publicly_viewable(page: Any, request: Any) -> bool:
    """Return ``True`` when ``page`` is live and the request passes its restrictions.

    Walks the Wagtail view restrictions for the page (and its ancestors). A live
    page with no restrictions is publicly viewable.
    """
    if page is None or not getattr(page, "live", False):
        return False
    return all(restriction.accept_request(request) for restriction in page.get_view_restrictions())


def page_is_unrestricted_public(page: Any) -> bool:
    """Return ``True`` when ``page`` is live and has no view restrictions.

    This is stricter than ``page_is_publicly_viewable``: a logged-in request may
    be allowed through a login/group/password restriction, but that response is
    still request-specific and must not be stored in shared public caches.
    """
    if page is None or not getattr(page, "live", False):
        return False
    return not page.get_view_restrictions().exists()


def user_can_edit_page(page: Any, user: Any) -> bool:
    """Return ``True`` when ``user`` may edit ``page`` (covers preview/draft access)."""
    if page is None or user is None or not getattr(user, "is_authenticated", False):
        return False
    return bool(page.permissions_for_user(user).can_edit())


def _page_references_audio(page: Any, audio: Any) -> bool:
    """Return ``True`` when ``page`` references ``audio`` as podcast or body audio."""
    audio_pk = audio.pk
    specific = getattr(page, "specific", page)
    if getattr(specific, "podcast_audio_id", None) == audio_pk:
        return True
    return audio_pk in specific.media_lookup.get("audio", {})


def _request_user(request: Any) -> Any:
    return getattr(request, "user", None)


def request_may_view_page(page: Any, request: Any) -> bool:
    """True when the request may view ``page`` publicly or as an authorized editor."""
    specific = getattr(page, "specific", page)
    return page_is_publicly_viewable(specific, request) or user_can_edit_page(specific, _request_user(request))


def page_grants_audio_access(page: Any, audio: Any, request: Any) -> bool:
    """A page grants access if it references the audio and is viewable or editable."""
    if not _page_references_audio(page, audio):
        return False
    return request_may_view_page(page, request)


def _resolve_page(anchor_id: Any) -> Any | None:
    """Resolve an episode/post pk to its specific page, or ``None`` when invalid."""
    from .models import Post

    try:
        anchor_pk = int(anchor_id)
    except (TypeError, ValueError):
        return None
    try:
        return Post.objects.get(pk=anchor_pk).specific
    except Post.DoesNotExist:
        return None


def authorize_audio_access(request: Any, *, audio: Any, explicit_anchor_id: Any = None) -> Any:
    """Authorize access to ``audio``'s public media or raise ``Http404``.

    ``explicit_anchor_id`` is an episode/post pk supplied by the caller
    (``episode_id``/``post_id``). When present it must resolve to a page that
    references the audio and grants access; an absent, unresolved, mismatched, or
    unauthorized anchor is a 404. When no anchor is supplied, any live episode
    referencing the audio that grants access is sufficient.

    Returns the granting page (callers may reuse it for sanitization context).
    """
    if explicit_anchor_id is not None:
        page = _resolve_page(explicit_anchor_id)
        if page is not None and page_grants_audio_access(page, audio, request):
            return page
        raise Http404("no authorized anchor for this audio")

    for episode in audio.episodes.all():
        if page_grants_audio_access(episode, audio, request):
            return episode
    raise Http404("no public episode references this audio")


def authorize_transcript_access(request: Any, *, transcript: Any, explicit_anchor_id: Any = None) -> Any:
    """Authorize access to ``transcript``'s public content or raise ``Http404``."""
    audio = getattr(transcript, "audio", None)
    return authorize_audio_access(request, audio=audio, explicit_anchor_id=explicit_anchor_id)
