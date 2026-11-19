from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from queue import Empty, Queue
from threading import Thread
from typing import BinaryIO

_probe_deadline: ContextVar[float | None] = ContextVar("cast_probe_deadline", default=None)


@contextmanager
def media_probe_budget(seconds: float) -> Iterator[None]:
    """Apply a cumulative subprocess budget to nested media probing calls."""
    deadline = time.monotonic() + seconds
    parent_deadline = _probe_deadline.get()
    if parent_deadline is not None:
        deadline = min(deadline, parent_deadline)
    token = _probe_deadline.set(deadline)
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


PROBE_STDOUT_LIMIT = 1024 * 1024
PROBE_STDERR_LIMIT = 64 * 1024


class MediaProbeOutputTooLarge(subprocess.CalledProcessError):
    """The subprocess exceeded one of the captured output limits."""

    def __init__(self, program: str, stream: str, limit: int) -> None:
        super().__init__(1, program)
        self.stream = stream
        self.limit = limit

    def __str__(self) -> str:
        return f"Media probe {self.stream} exceeded {self.limit} bytes"


def _read_probe_stream(
    pipe: BinaryIO,
    program: str,
    stream: str,
    limit: int,
    results: Queue[tuple[str, bytes | Exception]],
) -> None:
    output = bytearray()
    try:
        while len(output) <= limit:
            chunk = pipe.read(min(64 * 1024, limit + 1 - len(output)))
            if not chunk:
                results.put((stream, bytes(output)))
                return
            output.extend(chunk)
        raise MediaProbeOutputTooLarge(program, stream, limit)
    except (OSError, ValueError, MediaProbeOutputTooLarge) as exc:
        results.put((stream, exc))


def run_media_probe(command: Sequence[str], *, timeout: float = 30) -> subprocess.CompletedProcess[bytes]:
    """Capture separately bounded byte streams using the active cumulative budget."""
    timeout = remaining_probe_timeout(timeout)
    deadline = time.monotonic() + timeout
    results: Queue[tuple[str, bytes | Exception]] = Queue()
    output: dict[str, bytes] = {}
    # Raw pipes let cleanup close them without waiting on a buffered reader's lock.
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0) as process:
        assert process.stdout is not None and process.stderr is not None
        try:
            for stream, pipe, limit in (
                ("stdout", process.stdout, PROBE_STDOUT_LIMIT),
                ("stderr", process.stderr, PROBE_STDERR_LIMIT),
            ):
                Thread(target=_read_probe_stream, args=(pipe, command[0], stream, limit, results), daemon=True).start()

            for _ in range(2):
                try:
                    stream, result = results.get(timeout=max(0, deadline - time.monotonic()))
                except Empty:
                    raise subprocess.TimeoutExpired(command, timeout) from None
                if isinstance(result, Exception):
                    raise result
                output[stream] = result
            returncode = process.wait(timeout=max(0, deadline - time.monotonic()))
        except BaseException:
            process.kill()
            raise

    result_process = subprocess.CompletedProcess(command, returncode, output["stdout"], output["stderr"])
    result_process.check_returncode()
    return result_process


# ffmpeg protocols an input may use, including everything the input itself
# references (playlists, concat lists, ...). Local files may only open local
# files, and storage URLs may only open network resources (``httpproxy`` lets
# HTTPS tunnel through a configured ``http_proxy``). Paths and hosts within
# those protocols are not restricted.
LOCAL_INPUT_PROTOCOLS = "file"
REMOTE_INPUT_PROTOCOLS = "http,https,tcp,tls,httpproxy"


def input_protocol_args(source: str | os.PathLike[str]) -> list[str]:
    """Return the ``-protocol_whitelist`` option for an ffmpeg/ffprobe input."""
    if str(source).lower().startswith(("http://", "https://")):
        return ["-protocol_whitelist", REMOTE_INPUT_PROTOCOLS]
    return ["-protocol_whitelist", LOCAL_INPUT_PROTOCOLS]
