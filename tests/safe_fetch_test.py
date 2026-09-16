import io
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from cast.safe_fetch import FetchError, FetchPolicy, NoRedirectHandler, ResponseTooLarge, fetch_bytes, open_url


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def read(self, size: int = -1) -> bytes:
        return self.content if size < 0 else self.content[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def policy(**overrides):
    values = {
        "allowed_origins": frozenset({("https", "media.example")}),
        "max_bytes": 4,
        "max_error_bytes": 4,
        "timeout": 2.5,
    }
    values.update(overrides)
    return FetchPolicy(**values)


def test_fetch_bytes_refuses_redirect_response(mocker):
    error = HTTPError(
        url="https://media.example/start",
        code=302,
        msg="Found",
        hdrs=None,
        fp=io.BytesIO(b"next"),
    )
    open_url = mocker.patch("cast.safe_fetch.open_url", side_effect=error)

    with pytest.raises(FetchError, match="302: next"):
        fetch_bytes("https://media.example/start", policy=policy())

    assert open_url.call_args.kwargs["follow_redirects"] is False


def test_fetch_bytes_refuses_disallowed_or_non_http_origin(mocker):
    open_url = mocker.patch("cast.safe_fetch.open_url")

    with pytest.raises(FetchError, match="origin is not allowed"):
        fetch_bytes("https://other.example/file", policy=policy())
    with pytest.raises(FetchError, match="HTTP or HTTPS"):
        fetch_bytes("file:///tmp/file", policy=policy(allowed_origins=None))

    open_url.assert_not_called()


def test_fetch_bytes_enforces_response_size_and_forwards_request_options(mocker):
    open_url = mocker.patch("cast.safe_fetch.open_url", return_value=FakeResponse(b"12345"))

    with pytest.raises(ResponseTooLarge, match="4 bytes"):
        fetch_bytes(
            "https://media.example/file",
            policy=policy(allowed_origins=None, follow_redirects=True),
            headers={"Accept": "application/json"},
            method="POST",
            data=b"request",
        )

    request = open_url.call_args.args[0]
    assert request.get_header("Accept") == "application/json"
    assert request.data == b"request"
    assert request.method == "POST"
    assert open_url.call_args.kwargs == {"timeout": 2.5, "follow_redirects": True}


def test_fetch_bytes_refuses_redirects_with_origin_allowlist(mocker):
    open_url = mocker.patch("cast.safe_fetch.open_url")

    with pytest.raises(ValueError, match="origin allowlist"):
        policy(follow_redirects=True)

    open_url.assert_not_called()


def test_fetch_bytes_bounds_http_error_detail(mocker):
    error = HTTPError(
        url="https://media.example/file",
        code=500,
        msg="Server Error",
        hdrs=None,
        fp=io.BytesIO(b"abcdef"),
    )
    mocker.patch("cast.safe_fetch.open_url", side_effect=error)

    with pytest.raises(FetchError, match=r"500: abcd \[truncated\]"):
        fetch_bytes("https://media.example/file", policy=policy())


def test_fetch_bytes_wraps_url_error(mocker):
    mocker.patch("cast.safe_fetch.open_url", side_effect=URLError("offline"))

    with pytest.raises(FetchError, match="offline"):
        fetch_bytes("https://media.example/file", policy=policy())


def test_open_url_without_redirects_uses_no_redirect_opener(mocker):
    opener = mocker.Mock()
    opener.open.return_value = FakeResponse(b"ok")
    build_opener = mocker.patch("cast.safe_fetch.build_opener", return_value=opener)
    request = Request("https://media.example/file")

    response = open_url(request, timeout=1.0, follow_redirects=False)

    assert response.read() == b"ok"
    assert build_opener.call_args.args == (NoRedirectHandler,)
    opener.open.assert_called_once_with(request, timeout=1.0)


def test_no_redirect_handler_blocks_redirect():
    handler = NoRedirectHandler()

    assert handler.redirect_request(None, None, 302, "Found", {}, "https://media.example/next") is None
