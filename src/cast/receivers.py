"""Signal receivers registered by ``CastConfig.ready()``."""

from typing import Any

from django.db import transaction


def rotate_feed_cache_on_view_restriction_change(sender: type, **kwargs: Any) -> None:
    """Retire every cached feed once a page view restriction change commits.

    The built-in feed routes sit behind a five-minute response cache. Their
    restricted-root guard runs before the cache, but an entry restricted after a
    feed was cached would otherwise stay listed, with its content and
    enclosure, until the cached response expires.

    Rotating the feed cache generation changes every feed's cache key with one
    cache write. It runs on commit so another worker cannot refill the cache
    from the pre-change state, and a render that was already in flight stores
    its response under the old generation, where no later request reads it
    (see ``cast.feeds.restriction_aware_cache_page``).
    """
    from .feeds import rotate_feed_cache_generation

    transaction.on_commit(rotate_feed_cache_generation, using=kwargs.get("using"))


def connect_receivers() -> None:
    from django.db.models.signals import post_delete, post_save
    from wagtail.models import PageViewRestriction

    for signal, name in ((post_save, "saved"), (post_delete, "deleted")):
        signal.connect(
            rotate_feed_cache_on_view_restriction_change,
            sender=PageViewRestriction,
            dispatch_uid=f"cast_rotate_feed_cache_on_view_restriction_{name}",
        )
