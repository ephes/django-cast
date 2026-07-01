from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_probe_deadline: ContextVar[float | None] = ContextVar("cast_probe_deadline", default=None)


@contextmanager
def media_probe_budget(seconds: float) -> Iterator[None]:
    """Apply a cumulative subprocess budget to nested media probing calls."""
    token = _probe_deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _probe_deadline.reset(token)


def remaining_probe_timeout(default: float) -> float:
    deadline = _probe_deadline.get()
    if deadline is None:
        return default
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(cmd="media probe budget", timeout=0)
    return min(default, remaining)


def media_probe_budget_active() -> bool:
    """Return whether the current context is inside a cumulative media probe budget."""
    return _probe_deadline.get() is not None


def run_media_probe(command: Sequence[str], *, timeout: float = 30, **kwargs: Any) -> subprocess.CompletedProcess:
    """Run an ffprobe/ffmpeg command using the active cumulative budget."""
    return subprocess.run(command, timeout=remaining_probe_timeout(timeout), **kwargs)
