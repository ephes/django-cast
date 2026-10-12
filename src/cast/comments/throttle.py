"""Rate limit for posting comments.

Posting is open to anonymous visitors, and a comment form's security hash stays
valid for hours, so without a limit a single client could flood threads and the
moderation queue. The limit builds on Django REST framework's
``SimpleRateThrottle`` (sliding window, cache-backed) and its client
identification, which honours ``REST_FRAMEWORK["NUM_PROXIES"]``.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from django.http import HttpRequest
from rest_framework.throttling import SimpleRateThrottle

from . import appsettings


class CommentPostThrottle(SimpleRateThrottle):
    """Limit comment posts per authenticated user, or per client address."""

    scope = "cast_comment_post"

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
