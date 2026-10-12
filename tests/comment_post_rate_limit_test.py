import itertools

import django_comments
import pytest
from django.test import Client
from django.urls import reverse

from cast import checks as cast_checks
from cast.comments.throttle import CommentPostThrottle

from .factories import UserFactory

pytestmark = pytest.mark.django_db

# The test cache is shared by the whole run: every test posts from its own address.
_addresses = (f"198.51.100.{n}" for n in itertools.count(1))
# Identical comments are collapsed into one, so every post gets its own text.
_texts = (f"new content {n}" for n in itertools.count(1))


@pytest.fixture
def address():
    return next(_addresses)


@pytest.fixture
def limit_two(settings):
    settings.CAST_COMMENTS_POST_RATE_LIMIT = 2
    settings.CAST_COMMENTS_POST_RATE_WINDOW = 600


def comment_data(post, **extra):
    form = django_comments.get_form()(post)
    return {
        **form.generate_security_data(),
        "comment": next(_texts),
        "name": "Name",
        "email": "name@example.org",
        "title": "",
        **extra,
    }


def post_ajax(client, post, address, **extra):
    return client.post(
        reverse("comments-post-comment-ajax"),
        comment_data(post, **extra),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        REMOTE_ADDR=address,
    )


def post_plain(client, post, address, **extra):
    return client.post(reverse("comments-post-comment"), comment_data(post, **extra), REMOTE_ADDR=address)


def comment_count():
    return django_comments.get_model().objects.count()


def test_ajax_posts_over_the_limit_are_refused(client, post, comments_enabled, limit_two, address):
    assert [post_ajax(client, post, address).status_code for _ in range(2)] == [200, 200]

    response = post_ajax(client, post, address)

    assert response.status_code == 429
    assert int(response["Retry-After"]) >= 1
    payload = response.json()
    assert payload["success"] is False
    assert "comment" in payload["errors"]
    assert payload["object_id"] == str(post.pk)
    assert comment_count() == 2


def test_plain_posts_over_the_limit_are_refused(client, post, comments_enabled, limit_two, address):
    assert [post_plain(client, post, address).status_code for _ in range(2)] == [302, 302]

    response = post_plain(client, post, address)

    assert response.status_code == 429
    assert int(response["Retry-After"]) >= 1
    assert response["Content-Type"].startswith("text/plain")
    assert comment_count() == 2


def test_both_post_views_share_one_budget(client, post, comments_enabled, limit_two, address):
    assert post_ajax(client, post, address).status_code == 200
    assert post_plain(client, post, address).status_code == 302

    assert post_ajax(client, post, address).status_code == 429
    assert post_plain(client, post, address).status_code == 429


def test_a_new_session_does_not_reset_the_limit(post, comments_enabled, limit_two, address):
    for _ in range(2):
        assert post_ajax(Client(), post, address).status_code == 200

    assert post_ajax(Client(), post, address).status_code == 429


def test_other_clients_are_not_affected(client, post, comments_enabled, limit_two, address):
    for _ in range(3):
        post_ajax(client, post, address)

    assert post_ajax(client, post, next(_addresses)).status_code == 200


def test_previews_are_not_counted_and_not_refused(client, post, comments_enabled, limit_two, address):
    for _ in range(3):
        assert post_ajax(client, post, address, preview="1").status_code == 200
    assert [post_ajax(client, post, address).status_code for _ in range(3)] == [200, 200, 429]

    assert post_ajax(client, post, address, preview="1").status_code == 200
    assert post_plain(client, post, address, preview="1").status_code == 200


def test_authenticated_users_are_limited_per_user(client, post, comments_enabled, limit_two, address):
    client.force_login(UserFactory())
    for _ in range(2):
        assert post_ajax(client, post, address).status_code == 200

    # Changing the address does not help a logged-in user ...
    assert post_ajax(client, post, next(_addresses)).status_code == 429
    # ... and anonymous visitors at the first address keep their own budget.
    client.logout()
    assert post_ajax(client, post, address).status_code == 200


def test_limit_zero_disables_the_limit(client, post, comments_enabled, settings, address):
    settings.CAST_COMMENTS_POST_RATE_LIMIT = 0

    assert [post_ajax(client, post, address).status_code for _ in range(4)] == [200] * 4


def test_default_limit_and_window(settings):
    del settings.CAST_COMMENTS_POST_RATE_LIMIT

    throttle = CommentPostThrottle()

    assert (throttle.num_requests, throttle.duration) == (20, 600)


@pytest.mark.parametrize(
    "name, value",
    [
        ("CAST_COMMENTS_POST_RATE_LIMIT", -1),
        ("CAST_COMMENTS_POST_RATE_LIMIT", "many"),
        ("CAST_COMMENTS_POST_RATE_WINDOW", 0),
    ],
)
def test_invalid_post_rate_settings_fail_the_system_check(settings, name, value):
    setattr(settings, name, value)

    assert [error.id for error in cast_checks.check_cast_comments_author_edits_tunables()] == ["cast.E007"]
