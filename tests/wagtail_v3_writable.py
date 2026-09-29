"""Test-only writable field opt-in for the Wagtail 8 v3 experiment."""

from copy import copy

from wagtail.api import APIField

from cast.models import Episode, Post

POST_WRITABLE_FIELDS = frozenset({"visible_date", "cover_alt_text", "body"})
EPISODE_ONLY_WRITABLE_FIELDS = frozenset({"episode_number", "episode_type", "keywords", "explicit", "block"})
# Wagtail's own scheduling fields are not in v3's base page inventory.
SCHEDULE_WRITABLE_FIELDS = frozenset({"go_live_at", "expire_at"})


def enable_test_writes() -> None:
    """Expose a minimal scalar inventory before v3 builds its schemas."""
    Post.api_fields = [copy(field) for field in Post.api_fields]
    Post.api_fields.extend(APIField(name) for name in sorted(SCHEDULE_WRITABLE_FIELDS))
    for field in Post.api_fields:
        field.writable = field.name in POST_WRITABLE_FIELDS | SCHEDULE_WRITABLE_FIELDS

    episode_fields = {field.name: copy(field) for field in Post.api_fields}
    episode_fields.update({field.name: copy(field) for field in Episode.__dict__.get("api_fields", ())})
    for name in sorted(EPISODE_ONLY_WRITABLE_FIELDS):
        episode_fields.setdefault(name, APIField(name))
    for field in episode_fields.values():
        field.writable = field.name in POST_WRITABLE_FIELDS | SCHEDULE_WRITABLE_FIELDS | EPISODE_ONLY_WRITABLE_FIELDS
    Episode.api_fields = list(episode_fields.values())
