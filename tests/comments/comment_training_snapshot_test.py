"""Training reads author deletion and moderation state on one database snapshot."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection
from django.urls import reverse
from django_comments import get_model

from cast.comments import author_edits
from cast.models.moderation import SpamFilter
from tests.comments.comment_author_edits_helpers import AJAX, seed_ownership


@pytest.mark.django_db(transaction=True)
def test_author_deletion_committed_before_corpus_read_is_excluded(client, comment, comment_spam, settings):
    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
    settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 0
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    seed_ownership(client, comment)
    reading, resume = threading.Event(), threading.Event()
    reader_connections = []
    table = connection.ops.quote_name(get_model()._meta.db_table)

    def collect():
        close_old_connections()
        try:

            def pause(execute, sql, params, many, context):
                # On the old implementation, the deletion PK set has already
                # been read here. The fix reads both states in this statement.
                if sql.startswith("SELECT") and f"FROM {table}" in sql:
                    reader_connections.append(connection.connection)
                    reading.set()
                    assert resume.wait(10), "Deletion did not finish"
                return execute(sql, params, many, context)

            with connection.execute_wrapper(pause):
                return SpamFilter.get_training_data_comments()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(collect)
        try:
            assert reading.wait(10), "Training never reached the comment read"
            assert reader_connections[0] is not connection.connection
            response = client.post(reverse("comments-delete-comment-ajax"), {"comment_id": str(comment.pk)}, **AJAX)
            assert response.status_code == 200
            assert str(comment.pk) in author_edits.deleted_comment_pks()
        finally:
            resume.set()
        train = future.result(timeout=15)

    comment.refresh_from_db()
    assert comment.is_removed and not comment.is_public
    assert train == [("spam", SpamFilter.comment_to_message(comment_spam))]


@pytest.mark.django_db
def test_corpus_uses_one_projected_query(comment, comment_spam, django_assert_num_queries):
    with django_assert_num_queries(1):
        train = SpamFilter.get_training_data_comments()
    assert sorted(train) == sorted(
        [("ham", SpamFilter.comment_to_message(comment)), ("spam", SpamFilter.comment_to_message(comment_spam))]
    )


@pytest.mark.django_db
@pytest.mark.parametrize("full_name", ["", "Synthetic Author"])
def test_corpus_keeps_authenticated_identity_in_same_query(comment, user, full_name, django_assert_num_queries):
    user.first_name = full_name
    user.save()
    comment.user = user
    comment.save()
    with django_assert_num_queries(1):
        train = SpamFilter.get_training_data_comments()
    assert train == [("ham", f"{full_name or user.get_username()} {user.email} {comment.title} {comment.comment}")]
