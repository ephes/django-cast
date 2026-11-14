"""Atomic cache-slot admission for public comment posts.

Each allowed post owns one expiring slot. Client identification continues to use
DRF's trusted proxy rules; author edit/delete throttling has a separate budget.
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Any

from django.core.cache import caches
from django.core.cache.backends.locmem import LocMemCache
from django.core.cache.backends.memcached import PyLibMCCache, PyMemcacheCache
from django.core.cache.backends.redis import RedisCache
from django.http import HttpRequest
from rest_framework.throttling import SimpleRateThrottle

from . import appsettings

logger = logging.getLogger(__name__)
ATOMIC_ADD_BACKENDS = (LocMemCache, RedisCache, PyLibMCCache, PyMemcacheCache)


class CommentPostThrottle(SimpleRateThrottle):
    """Limit comment posts per authenticated user, or per client address."""

    scope = "cast_comment_post"

    def allow_request(self, request: HttpRequest, view: Any) -> bool:
        if self.rate is None:
            return True
        key = self.get_cache_key(request, view)
        assert self.num_requests is not None
        try:
            cache = caches["default"]
            if type(cache) not in ATOMIC_ADD_BACKENDS:
                logger.warning("Comment posting requires a supported atomic-add cache backend")
                return False
            for slot in range(self.num_requests):
                if cache.add(f"{key}:slot:{slot}", True, timeout=self.duration):
                    return True
        except Exception:
            logger.warning("Comment post cache reservation unavailable")
        return False

    def wait(self) -> float | None:
        # A full window is a conservative retry bound; refusals never extend it.
        return self.duration

    def get_rate(self) -> str | None:
        limit = appsettings.POST_RATE_LIMIT
        if limit <= 0:
            return None  # disabled: SimpleRateThrottle allows every request
        return f"{limit}/{appsettings.POST_RATE_WINDOW}"

    def parse_rate(self, rate: str | None) -> tuple[int | None, int | None]:
        if rate is None:
            return (None, None)
        return (appsettings.POST_RATE_LIMIT, appsettings.POST_RATE_WINDOW)

    def get_cache_key(self, request: HttpRequest, view: Any) -> str:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            ident = f"user:{user.pk}"
        else:
            ident = f"client:{self.get_ident(request)}"
        # Hash so that arbitrary header input always yields a valid cache key.
        digest = hashlib.sha256(ident.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}


def comment_post_retry_after(request: HttpRequest) -> int | None:
    """Check the client's comment post budget, counting the post if allowed.

    Returns ``None`` when the post is allowed, otherwise the number of seconds
    after which the client may try again.
    """
    throttle = CommentPostThrottle()
    if throttle.allow_request(request, None):
        return None
    return max(math.ceil(throttle.wait() or 1), 1)
