"""Test-only writable field opt-in for the Wagtail 8 v3 experiment."""

from copy import copy

from wagtail.api import APIField

from cast.models import Episode, Post

POST_WRITABLE_FIELDS = frozenset({"visible_date", "cover_alt_text"})
EPISODE_ONLY_WRITABLE_FIELDS = frozenset({"episode_number", "episode_type", "keywords", "explicit", "block"})


def enable_test_writes() -> None:
    """Expose a minimal scalar inventory before v3 builds its schemas."""
    Post.api_fields = [copy(field) for field in Post.api_fields]
    for field in Post.api_fields:
        field.writable = field.name in POST_WRITABLE_FIELDS

    episode_fields = {field.name: copy(field) for field in Post.api_fields}
    episode_fields.update({field.name: copy(field) for field in Episode.__dict__.get("api_fields", ())})
    for name in sorted(EPISODE_ONLY_WRITABLE_FIELDS):
        episode_fields.setdefault(name, APIField(name))
    for field in episode_fields.values():
        field.writable = field.name in POST_WRITABLE_FIELDS | EPISODE_ONLY_WRITABLE_FIELDS
    Episode.api_fields = list(episode_fields.values())
