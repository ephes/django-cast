"""Session ownership does not preserve revoked access to a comment's page."""

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.test import RequestFactory
from django.urls import reverse
from django_comments import signals
from wagtail.models import PageViewRestriction

from cast.comments import author_edits
from cast.comments.models import CommentAuthorMeta
from tests.comment_author_edits_test import AJAX, seed_ownership
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def enable_author_actions(settings):
    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 0


@pytest.fixture(params=["edit", "delete"])
def action(request):
    return request.param


def submit(client, comment, action):
    return client.post(
        reverse(f"comments-{action}-comment-ajax"),
        {"comment_id": str(comment.pk), "comment": "Author replacement"},
        **AJAX,
    )


def controls(client, comment, user=None):
    request = RequestFactory().get("/")
    request.session = client.session
    request.user = user or AnonymousUser()
    comment.refresh_from_db()
    return author_edits.comment_action_context(request, comment)


def stored_state(comment):
    return (
        type(comment).objects.filter(pk=comment.pk).values().get(),
        list(CommentAuthorMeta.objects.filter(comment_pk=str(comment.pk)).values()),
    )


@pytest.mark.parametrize(
    ("revocation", "inherited"),
    [
        ("unpublish", False),
        ("login", False),
        ("login", True),
        ("groups", False),
        ("groups", True),
        ("password", False),
        ("password", True),
    ],
)
def test_author_actions_recheck_revoked_access(client, post, comment, action, revocation, inherited, mocker):
    seed_ownership(client, comment)
    assert controls(client, comment)["can_edit"]
    if revocation == "unpublish":
        # Unpublishing an ancestor does not unpublish its children in Wagtail.
        post.unpublish()
    else:
        PageViewRestriction.objects.create(
            page=post.get_parent() if inherited else post, restriction_type=revocation, password="secret"
        )
    author_edits.mark_edited(comment)
    before = stored_state(comment)
    moderation = mocker.spy(signals.comment_will_be_posted, "send")

    response = submit(client, comment, action)

    assert response.status_code == 403
    assert response.content == b"This comment cannot be edited or deleted."
    assert stored_state(comment) == before
    moderation.assert_not_called()
    assert controls(client, comment) == {"can_edit": False, "can_delete": False, "edited": True}


@pytest.mark.parametrize("restriction_type", ["login", "groups", "password"])
@pytest.mark.parametrize("inherited", [False, True])
def test_authorized_restricted_authors_keep_actions(client, post, comment, action, restriction_type, inherited):
    restriction = PageViewRestriction.objects.create(
        page=post.get_parent() if inherited else post, restriction_type=restriction_type, password="secret"
    )
    user = None
    if restriction_type == "password":
        session = client.session
        session[restriction.passed_view_restrictions_session_key] = [restriction.pk]
        session.save()
    else:
        user = UserFactory()
        if restriction_type == "groups":
            group = Group.objects.create(name="Comment authors with page access")
            restriction.groups.add(group)
            user.groups.add(group)
        client.force_login(user)
    seed_ownership(client, comment)
    assert controls(client, comment, user)["can_edit"]
    assert controls(client, comment, user)["can_delete"]

    response = submit(client, comment, action)

    assert response.status_code == 200, response.content
    comment.refresh_from_db()
    if action == "edit":
        assert comment.comment == "Author replacement"
        assert CommentAuthorMeta.objects.get(comment_pk=str(comment.pk)).edited
    else:
        assert comment.is_removed and not comment.is_public
        assert CommentAuthorMeta.objects.get(comment_pk=str(comment.pk)).deleted_at is not None


def test_lost_group_membership_revokes_author_actions(client, post, comment, action):
    user = UserFactory()
    group = Group.objects.create(name="Former readers")
    restriction = PageViewRestriction.objects.create(page=post, restriction_type="groups")
    restriction.groups.add(group)
    user.groups.add(group)
    client.force_login(user)
    seed_ownership(client, comment)
    assert controls(client, comment, user)["can_edit"]
    user.groups.remove(group)
    before = stored_state(comment)
    assert submit(client, comment, action).status_code == 403
    assert stored_state(comment) == before
    assert not controls(client, comment, user)["can_edit"]


def test_direct_access_does_not_override_inherited_restriction(client, post, comment, action):
    user = UserFactory()
    client.force_login(user)
    seed_ownership(client, comment)
    PageViewRestriction.objects.create(page=post, restriction_type="login")
    PageViewRestriction.objects.create(page=post.get_parent(), restriction_type="groups")
    before = stored_state(comment)
    assert submit(client, comment, action).status_code == 403
    assert stored_state(comment) == before
    assert not controls(client, comment, user)["can_delete"]


def test_superuser_ownership_does_not_bypass_unpublished_page(client, post, comment, action, admin_user):
    client.force_login(admin_user)
    seed_ownership(client, comment)
    post.unpublish()
    before = stored_state(comment)
    assert submit(client, comment, action).status_code == 403
    assert stored_state(comment) == before
    assert not controls(client, comment, admin_user)["can_edit"]


@pytest.mark.parametrize("target_kind", ["generic", "missing-page", "missing-generic"])
def test_generic_and_missing_targets(client, comment, action, target_kind):
    if target_kind != "missing-page":
        target = Group.objects.create(name="Non-page comment target")
        comment.content_object = target
    else:
        comment.object_pk = "999999"
    comment.save()
    if target_kind == "missing-generic":
        target.delete()
    seed_ownership(client, comment)
    before = stored_state(comment)
    flags = controls(client, comment)

    response = submit(client, comment, action)

    if target_kind == "generic":
        assert response.status_code == 200, response.content
        assert flags["can_edit"] and flags["can_delete"]
    else:
        assert response.status_code == 403
        assert response.content == b"This comment cannot be edited or deleted."
        assert stored_state(comment) == before
        assert not flags["can_edit"] and not flags["can_delete"]
