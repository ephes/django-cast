"""Ajax acceptance separates required ownership from post-commit observers."""

from unittest.mock import Mock

import pytest
from django.db import transaction
from django_comments import get_model, signals

from cast.comments import author_edits
from tests.comment_page_access_test import comment_payload, submit


@pytest.fixture
def observer():
    # A real named receiver also exercises Django's supported robust dispatch.
    calls = Mock()

    def receiver(sender, comment, **kwargs):
        calls(comment.pk)
        raise RuntimeError("synthetic observer failure")

    signals.comment_was_posted.connect(receiver, weak=False)
    yield calls
    signals.comment_was_posted.disconnect(receiver)


@pytest.mark.django_db
@pytest.mark.parametrize("reply", [False, True])
def test_optional_observer_failure_accepts_once(
    client, post, settings, comments_enabled, observer, django_capture_on_commit_callbacks, caplog, reply
):
    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
    data = comment_payload(post, False)
    if reply:
        parent = get_model().objects.create(content_object=post, site_id=settings.SITE_ID, comment="Parent")
        data["parent"] = str(parent.pk)
    before = get_model().objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        response = submit(client, "comments-post-comment-ajax", data)
        observer.assert_not_called()
    assert response.status_code == 200
    assert response.json()["success"] is True
    pk = response.json()["comment_id"]
    assert get_model().objects.count() == before + 1
    observer.assert_called_once_with(int(pk))
    assert str(pk) in client.session[author_edits.SESSION_KEY]
    assert "1 comment observer(s) failed" in caplog.text


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("rollback", [False, True])
def test_observers_follow_outer_transaction(client, pg_editor_actors, comments_enabled, observer, rollback):
    from tests.factories import PostFactory

    _, blog = pg_editor_actors
    post = PostFactory(parent=blog, title="Synthetic comment target", slug="comment-target", body=[])
    data = comment_payload(post, False)
    before = get_model().objects.count()
    with transaction.atomic():
        response = submit(client, "comments-post-comment-ajax", data)
        assert response.status_code == 200
        observer.assert_not_called()
        if rollback:
            transaction.set_rollback(True)
    if rollback:
        observer.assert_not_called()
        assert get_model().objects.count() == before
    else:
        observer.assert_called_once_with(int(response.json()["comment_id"]))
        assert get_model().objects.count() == before + 1


@pytest.mark.django_db
def test_core_ownership_failure_rolls_back(client, post, settings, comments_enabled, observer, mocker):
    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
    failure = mocker.patch.object(author_edits, "record_owned_id", side_effect=RuntimeError("ownership failed"))
    before = get_model().objects.count()
    with pytest.raises(RuntimeError, match="ownership failed"):
        submit(client, "comments-post-comment-ajax", comment_payload(post, False))
    failure.assert_called_once()
    observer.assert_not_called()
    assert get_model().objects.count() == before


@pytest.mark.django_db
def test_successful_observer_runs_after_commit(
    client, post, comments_enabled, django_capture_on_commit_callbacks, caplog
):
    calls = []

    def receiver(sender, comment, **kwargs):
        calls.append(comment.pk)

    signals.comment_was_posted.connect(receiver)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            response = submit(client, "comments-post-comment-ajax", comment_payload(post, False))
            assert calls == []
        assert response.status_code == 200
        assert calls == [int(response.json()["comment_id"])]
        assert "comment observer(s) failed" not in caplog.text
    finally:
        signals.comment_was_posted.disconnect(receiver)
