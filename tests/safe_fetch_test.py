import io
from socket import SOCK_STREAM
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
        "block_private_addresses": False,
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


def test_fetch_policy_refuses_redirects_with_private_address_blocking():
    with pytest.raises(ValueError, match="private-address blocking"):
        policy(allowed_origins=None, follow_redirects=True, block_private_addresses=True)


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


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.1.1",
        "::1",
        "fc00::1",
        "ff02::1",
    ],
)
def test_fetch_bytes_refuses_private_or_non_global_addresses(mocker, address):
    mocker.patch(
        "cast.safe_fetch.getaddrinfo",
        return_value=[(None, None, None, None, (address, 443))],
    )
    open_url = mocker.patch("cast.safe_fetch.open_url")

    with pytest.raises(FetchError, match="private or non-global"):
        fetch_bytes(
            "https://media.example/file",
            policy=policy(block_private_addresses=True),
        )

    open_url.assert_not_called()


def test_fetch_policy_blocks_private_addresses_by_default(mocker):
    mocker.patch(
        "cast.safe_fetch.getaddrinfo",
        return_value=[(None, None, None, None, ("127.0.0.1", 443))],
    )
    default_policy = FetchPolicy(
        allowed_origins=None,
        max_bytes=4,
        timeout=2.5,
    )

    with pytest.raises(FetchError, match="private or non-global"):
        fetch_bytes("https://127.0.0.1/file", policy=default_policy)


@pytest.mark.parametrize("url", ["https://127.0.0.1/file", "https://[::1]/file"])
def test_fetch_bytes_rejects_private_ip_literals_with_real_resolver(url):
    with pytest.raises(FetchError, match="private or non-global"):
        fetch_bytes(url, policy=policy(allowed_origins=None, block_private_addresses=True))


def test_fetch_bytes_allows_only_public_resolved_addresses(mocker):
    getaddrinfo = mocker.patch(
        "cast.safe_fetch.getaddrinfo",
        return_value=[
            (None, None, None, None, ("93.184.216.34", 8443)),
            (None, None, None, None, ("2606:2800:220:1:248:1893:25c8:1946%eth0", 8443)),
        ],
    )
    open_url = mocker.patch("cast.safe_fetch.open_url", return_value=FakeResponse(b"ok"))

    result = fetch_bytes(
        "https://media.example:8443/file",
        policy=policy(allowed_origins=None, block_private_addresses=True),
    )

    assert result == b"ok"
    getaddrinfo.assert_called_once_with("media.example", 8443, type=SOCK_STREAM)
    open_url.assert_called_once()


@pytest.mark.parametrize(
    ("resolver_result", "message"),
    [
        (OSError("lookup failed"), "could not be resolved"),
        ([], "did not resolve"),
        ([(None, None, None, None, ("invalid", 443))], "invalid address"),
    ],
)
def test_fetch_bytes_refuses_resolution_failures(mocker, resolver_result, message):
    if isinstance(resolver_result, BaseException):
        mocker.patch("cast.safe_fetch.getaddrinfo", side_effect=resolver_result)
    else:
        mocker.patch("cast.safe_fetch.getaddrinfo", return_value=resolver_result)

    with pytest.raises(FetchError, match=message):
        fetch_bytes(
            "https://media.example/file",
            policy=policy(block_private_addresses=True),
        )


def test_fetch_bytes_refuses_invalid_port_before_resolution(mocker):
    getaddrinfo = mocker.patch("cast.safe_fetch.getaddrinfo")

    with pytest.raises(FetchError, match="invalid port"):
        fetch_bytes(
            "https://media.example:invalid/file",
            policy=policy(allowed_origins=None, block_private_addresses=True),
        )

    getaddrinfo.assert_not_called()


def test_fetch_bytes_refuses_missing_hostname_before_resolution(mocker):
    getaddrinfo = mocker.patch("cast.safe_fetch.getaddrinfo")

    with pytest.raises(FetchError, match="include a host"):
        fetch_bytes(
            "https://:443/file",
            policy=policy(allowed_origins=None, block_private_addresses=True),
        )

    getaddrinfo.assert_not_called()


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
