import pytest

from tests.factories import PostFactory


@pytest.fixture()
def post_in_podcast(podcast, body):
    return PostFactory(
        owner=podcast.owner,
        parent=podcast,
        title="test entry",
        slug="test-entry",
        body=body,
    )


@pytest.fixture(autouse=True)
def synthetic_remote_origins(settings, monkeypatch):
    from cast import safe_fetch

    settings.CAST_STYLEGUIDE_REMOTE_ALLOWED_ORIGINS = ["https://example.com", "https://another.example.org"]
    monkeypatch.setattr(safe_fetch, "getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("93.184.216.34", 443))])
