"""Target model admission precedes lookup; current policy follows moderation."""

import pytest
from django.contrib.auth.models import Group
from django.db.models import QuerySet
from django_comments import get_model, signals
from wagtail.models import PageViewRestriction

from cast.comments import author_edits
from cast.models import Post
from tests.comment_page_access_test import comment_payload, submit

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("endpoint", ["comments-post-comment", "comments-post-comment-ajax"])
def test_forbidden_model_has_no_lookup_or_existence_oracle(client, settings, endpoint, monkeypatch):
    settings.DEBUG = True
    group = Group.objects.create(name="Private synthetic row")
    original_get = QuerySet.get

    def guarded_get(queryset, *args, **kwargs):
        assert queryset.model is not Group, "Forbidden model was queried"
        return original_get(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "get", guarded_get)
    responses = [
        submit(client, endpoint, {"content_type": "auth.group", "object_pk": pk})
        for pk in [str(group.pk), "999999", "bad"]
    ]
    assert all(response.status_code == 400 for response in responses)
    assert len({response.content for response in responses}) == 1


@pytest.mark.parametrize("endpoint", ["comments-post-comment", "comments-post-comment-ajax"])
@pytest.mark.parametrize("reply", [False, True])
@pytest.mark.parametrize("change", ["close", "unpublish", "restrict", "delete"])
def test_moderation_cannot_publish_to_revoked_target(
    client, post, settings, comments_enabled, endpoint, reply, change, django_capture_on_commit_callbacks, mocker
):
    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
    data = comment_payload(post, False)
    model = get_model()
    if reply:
        parent = model.objects.create(content_object=post, site_id=settings.SITE_ID, comment="Parent")
        data["parent"] = str(parent.pk)
    before = model.objects.count()
    observer = mocker.Mock()
    signals.comment_was_posted.connect(observer)

    def revoke(sender, **kwargs):
        if change == "close":
            Post.objects.filter(pk=post.pk).update(comments_enabled=False)
        elif change == "unpublish":
            Post.objects.filter(pk=post.pk).update(live=False)
        elif change == "restrict":
            PageViewRestriction.objects.create(page=post, restriction_type="login")
        else:
            post.delete()

    signals.comment_will_be_posted.connect(revoke)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            response = submit(client, endpoint, data)
        assert response.status_code in (400, 403)
        assert model.objects.count() <= before
        assert not client.session.get(author_edits.SESSION_KEY)
        observer.assert_not_called()
    finally:
        signals.comment_will_be_posted.disconnect(revoke)
        signals.comment_was_posted.disconnect(observer)
