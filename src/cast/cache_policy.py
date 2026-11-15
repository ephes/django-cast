"""Cache admission capabilities and process-local fallback warnings."""

from __future__ import annotations

import logging
from threading import Lock

from django.core.cache.backends.locmem import LocMemCache
from django.core.cache.backends.memcached import PyLibMCCache, PyMemcacheCache
from django.core.cache.backends.redis import RedisCache

ATOMIC_ADD_BACKENDS = (LocMemCache, RedisCache, PyLibMCCache, PyMemcacheCache)
_warned: set[str] = set()
_warning_lock = Lock()


def warn_best_effort(logger: logging.Logger, operation: str) -> None:
    """Warn once per process and operation, including concurrent first requests."""
    with _warning_lock:
        if operation not in _warned:
            _warned.add(operation)
            logger.warning(
                "%s uses best-effort cache admission; concurrent requests may exceed the limit. "
                "Django's built-in Redis/Memcached backends make admission exact across workers. "
                "DummyCache cannot enforce limits.",
                operation,
            )
