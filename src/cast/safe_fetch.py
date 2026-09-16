"""Bounded HTTP fetch primitives for trusted and future remote importers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

if TYPE_CHECKING:
    from http.client import HTTPMessage
    from types import TracebackType
    from typing import IO, Protocol, Self, overload

    class ReadableResponse(Protocol):
        @overload
        def read(self) -> bytes: ...

        @overload
        def read(self, size: int, /) -> bytes: ...

        def __enter__(self) -> Self: ...

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> object: ...
else:
    ReadableResponse = Any


class FetchError(Exception):
    """A remote fetch was refused or failed."""


class ResponseTooLarge(FetchError):
    """A response exceeded its configured byte cap."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"Response exceeded the maximum size of {max_bytes} bytes.")


@dataclass(frozen=True)
class FetchPolicy:
    """Constrain one remote HTTP fetch."""

    allowed_origins: frozenset[tuple[str, str]] | None
    max_bytes: int
    timeout: float
    max_error_bytes: int = 16 * 1024
    follow_redirects: bool = False
    # Enforced by the private-address resolution check added in slice 8.
    block_private_addresses: bool = True

    def __post_init__(self) -> None:
        if self.allowed_origins is not None and self.follow_redirects:
            raise ValueError("Redirects cannot be followed with an origin allowlist.")


class NoRedirectHandler(HTTPRedirectHandler):
    """Prevent urllib from following redirects automatically."""

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        return None


def open_url(request: Request, *, timeout: float, follow_redirects: bool = True) -> ReadableResponse:
    """Open a request with explicit redirect behavior."""
    if follow_redirects:
        return urlopen(request, timeout=timeout)
    return build_opener(NoRedirectHandler).open(request, timeout=timeout)


def read_response_bytes(response: ReadableResponse, *, max_bytes: int | None = None) -> bytes:
    """Read a response, optionally enforcing a byte cap."""
    if max_bytes is None:
        return response.read()
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ResponseTooLarge(max_bytes)
    return data


def read_http_error_detail(exc: HTTPError, *, max_bytes: int) -> str:
    """Read a bounded HTTP error body for diagnostics."""
    data = exc.read(max_bytes + 1)
    if len(data) > max_bytes:
        data = data[:max_bytes]
        suffix = " [truncated]"
    else:
        suffix = ""
    detail = data.decode("utf-8", errors="replace").strip() or str(exc.reason)
    return f"{detail}{suffix}"


def fetch_bytes(
    url: str,
    *,
    policy: FetchPolicy,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
) -> bytes:
    """Fetch bounded bytes from an allowed HTTP(S) origin."""
    parts = urlsplit(url)
    origin = (parts.scheme.lower(), parts.netloc.lower())
    if origin[0] not in {"http", "https"} or not origin[1]:
        raise FetchError("Fetch URL must use HTTP or HTTPS.")
    if policy.allowed_origins is not None and origin not in policy.allowed_origins:
        raise FetchError("Fetch URL origin is not allowed.")
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with open_url(request, timeout=policy.timeout, follow_redirects=policy.follow_redirects) as response:
            return read_response_bytes(response, max_bytes=policy.max_bytes)
    except HTTPError as exc:
        detail = read_http_error_detail(exc, max_bytes=policy.max_error_bytes)
        raise FetchError(f"Fetch failed with status {exc.code}: {detail}") from exc
    except URLError as exc:
        raise FetchError(f"Fetch failed: {exc.reason}") from exc
