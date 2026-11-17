"""The comment flag route only admits comments the requester could already see."""

import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from django_comments import get_model
from django_comments.models import CommentFlag
from wagtail.models import PageViewRestriction

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

HIDDEN_NAME = "Hidden Author"
HIDDEN_TEXT = "text that only moderators may read"


def make_comment(post, settings, **extra):
    comment = get_model()(
        content_object=post,
        site_id=settings.SITE_ID,
        name=HIDDEN_NAME,
        comment=HIDDEN_TEXT,
        **extra,
    )
    comment.save()
    return comment


def flag_url(comment):
    return reverse("comments-flag", args=(comment.pk,))


@pytest.fixture
def member_client(client):
    client.force_login(UserFactory())
    return client


def assert_not_exposed(response):
    assert response.status_code == 404
    assert HIDDEN_NAME.encode() not in response.content
    assert HIDDEN_TEXT.encode() not in response.content


@pytest.mark.parametrize("hidden", [{"is_public": False}, {"is_removed": True}])
def test_hidden_comment_is_not_found_for_member(member_client, post, settings, hidden):
    comment = make_comment(post, settings, **hidden)
    assert_not_exposed(member_client.get(flag_url(comment)))
    assert_not_exposed(member_client.post(flag_url(comment)))
    assert not CommentFlag.objects.filter(comment_id=comment.pk).exists()


def test_comment_on_unpublished_post_is_not_found_for_member(member_client, post, settings):
    comment = make_comment(post, settings)
    post.unpublish()
    assert_not_exposed(member_client.get(flag_url(comment)))
    assert_not_exposed(member_client.post(flag_url(comment)))
    assert not CommentFlag.objects.filter(comment_id=comment.pk).exists()


def test_comment_on_restricted_post_is_not_found_for_member(member_client, post, settings):
    comment = make_comment(post, settings)
    restriction = PageViewRestriction.objects.create(page=post, restriction_type="groups")
    restriction.groups.add(Group.objects.create(name="members"))
    assert_not_exposed(member_client.get(flag_url(comment)))
    assert not CommentFlag.objects.filter(comment_id=comment.pk).exists()


def test_missing_comment_is_not_found(member_client):
    response = member_client.get(reverse("comments-flag", args=(999999,)))
    assert response.status_code == 404


def test_public_comment_can_still_be_flagged(member_client, post, settings):
    comment = make_comment(post, settings)
    response = member_client.get(flag_url(comment))
    assert response.status_code == 200
    assert HIDDEN_NAME.encode() in response.content

    response = member_client.post(flag_url(comment))
    assert response.status_code == 302
    assert CommentFlag.objects.filter(comment_id=comment.pk, flag=CommentFlag.SUGGEST_REMOVAL).count() == 1


def test_moderator_can_flag_hidden_comment(client, post, settings):
    moderator = UserFactory()
    moderator.user_permissions.add(
        Permission.objects.get(codename="can_moderate", content_type__app_label="django_comments")
    )
    client.force_login(moderator)
    comment = make_comment(post, settings, is_public=False)
    post.unpublish()

    assert client.get(flag_url(comment)).status_code == 200
    assert client.post(flag_url(comment)).status_code == 302
    assert CommentFlag.objects.filter(comment_id=comment.pk).count() == 1


def test_anonymous_user_is_sent_to_login(client, post, settings):
    comment = make_comment(post, settings, is_public=False)
    response = client.get(flag_url(comment))
    assert response.status_code == 302
    assert HIDDEN_TEXT.encode() not in response.content
