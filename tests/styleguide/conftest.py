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
