"""Author self-editing/deletion of comments, bound to the Django session.

The whole feature is opt-in via ``CAST_COMMENTS_ALLOW_AUTHOR_EDITS`` and only
operates on a server-side session backend. Ownership of a comment is proven
solely by the comment id (as a string) being present in the current session's
``cast_owned_comments`` list, never by anything the client supplies directly.
"""

from __future__ import annotations

from django.conf import settings

from . import appsettings

SESSION_KEY = "cast_owned_comments"

SIGNED_COOKIES_BACKEND = "django.contrib.sessions.backends.signed_cookies"


def uses_signed_cookie_sessions() -> bool:
    """True when the insecure client-side session backend is configured."""
    return getattr(settings, "SESSION_ENGINE", "") == SIGNED_COOKIES_BACKEND


def author_edits_enabled() -> bool:
    """Runtime guard: the feature is on only when enabled and safe.

    Returns ``False`` under the ``signed_cookies`` backend even when the flag is
    set, so an insecure configuration silently disables the feature rather than
    operating with a client-carried, non-revocable owned-ids list.
    """
    if not appsettings.ALLOW_AUTHOR_EDITS:
        return False
    if uses_signed_cookie_sessions():
        return False
    return True


def record_owned_id(session, pk) -> None:
    """Record ownership of a freshly created comment in the session.

    The comment's primary key is stored as a string (the JSON session serializer
    cannot serialize arbitrary PK objects such as UUIDs, and posted ids arrive as
    strings anyway). The list is capped to the most recent ``OWNED_IDS_CAP`` ids.
    """
    owned = list(session.get(SESSION_KEY, []))
    key = str(pk)
    if key in owned:
        # Idempotent: repeated signal delivery for the same comment must not
        # consume the cap or duplicate the entry.
        return
    owned.append(key)
    cap = appsettings.OWNED_IDS_CAP
    if cap > 0 and len(owned) > cap:
        owned = owned[-cap:]
    session[SESSION_KEY] = owned
    session.modified = True


def owns_id(session, pk) -> bool:
    """True when the current session created the comment with this id."""
    return str(pk) in session.get(SESSION_KEY, [])


def comment_has_reply(comment) -> bool:
    """True when another comment answers this one (any moderation state).

    Replies are counted regardless of visibility: a pending/spam reply could be
    approved later, and the parent must not have been edited or deleted in the
    meantime. Only meaningful with threadedcomments; flat comments have no parent.
    """
    if not appsettings.USE_THREADEDCOMMENTS:
        return False
    import django_comments

    # Query the same database the comment was loaded from (the edit/delete views
    # load and lock it on ``using``), so reply detection stays consistent on
    # multi-database setups.
    db = comment._state.db
    return django_comments.get_model().objects.using(db).filter(parent_id=comment.pk).exists()


def comment_is_actionable(comment) -> bool:
    """The non-ownership half of the eligibility predicate.

    A comment may be edited or deleted by its owner only while it is still
    publicly visible and has not been answered.
    """
    return bool(comment.is_public) and not bool(comment.is_removed) and not comment_has_reply(comment)


def _meta_model():
    # CommentAuthorMeta is a distinct model: its database is chosen by Django's
    # database router (the default DB in single-database deployments, which is the
    # supported configuration), not inherited from the comment's ``using`` override.
    # Metadata reads and writes therefore route consistently to the same database,
    # so the edited/deleted markers and spam-training exclusion stay coherent. We
    # deliberately do not force the comment's ``using`` here, which could target a
    # database that does not hold this table under a split multi-database router.
    from .models import CommentAuthorMeta

    return CommentAuthorMeta


def mark_edited(comment) -> None:
    """Record that a comment was edited by its author (persistent boolean)."""
    model = _meta_model()
    meta, _created = model.objects.get_or_create(comment_pk=str(comment.pk))
    if not meta.edited:
        meta.edited = True
        meta.save(update_fields=["edited"])


def mark_deleted(comment, when=None) -> None:
    """Record an author deletion so it can be excluded from spam training."""
    from django.utils import timezone

    model = _meta_model()
    meta, _created = model.objects.get_or_create(comment_pk=str(comment.pk))
    meta.deleted_at = when or timezone.now()
    meta.save(update_fields=["deleted_at"])


def clear_deleted(pk) -> None:
    """Clear the author-deletion marker (used when staff restore a comment)."""
    _meta_model().objects.filter(comment_pk=str(pk)).update(deleted_at=None)


def delete_meta(pk) -> None:
    """Remove the metadata row entirely (used when a comment is hard-deleted)."""
    _meta_model().objects.filter(comment_pk=str(pk)).delete()


def rate_limited(request, action: str) -> bool:
    """Cache-based per-session/IP rate limit for edit/delete (no new dependency).

    Counts every attempt (including denied ones) so the endpoint cannot be used
    to probe at high volume.
    """
    from django.core.cache import cache

    limit = appsettings.EDIT_RATE_LIMIT
    if limit <= 0:
        return False
    session = getattr(request, "session", None)
    ident = getattr(session, "session_key", None) or request.META.get("REMOTE_ADDR", "anon")
    key = f"cast_author_edit_rl:{action}:{ident}"
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, appsettings.EDIT_RATE_WINDOW)
        count = 1
    return count > limit


def deleted_comment_pks() -> set[str]:
    """The set of comment PKs (as strings) currently marked author-deleted."""
    model = _meta_model()
    return set(model.objects.filter(deleted_at__isnull=False).values_list("comment_pk", flat=True))


def edited_pks_for(pks) -> set[str]:
    """The subset of the given comment PKs that carry an ``edited`` marker."""
    wanted = {str(pk) for pk in pks}
    if not wanted:
        return set()
    model = _meta_model()
    return set(model.objects.filter(comment_pk__in=wanted, edited=True).values_list("comment_pk", flat=True))


def comment_action_context(request, comment, edited_pks=None) -> dict:
    """Per-comment UI flags for the templates: whether the current session may
    edit/delete this comment, and whether it carries an 'edited' marker."""
    if not author_edits_enabled():
        return {"can_edit": False, "can_delete": False, "edited": False}
    session = getattr(request, "session", None)
    owns = (
        author_edits_enabled()
        and session is not None
        and owns_id(session, comment.pk)
        and comment_is_actionable(comment)
    )
    if edited_pks is not None:
        edited = str(comment.pk) in edited_pks
    else:
        edited = bool(edited_pks_for([comment.pk]))
    return {"can_edit": owns, "can_delete": owns, "edited": edited}
