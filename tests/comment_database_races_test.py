"""Committed PostgreSQL reply/author-action journeys using independent connections."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection
from django.test import Client
from django.urls import reverse
from django_comments import get_form, get_model

from tests.comment_author_edits_test import AJAX, seed_ownership
from tests.factories import PostFactory


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL row-lock semantics")
@pytest.mark.parametrize("route", ["stock", "ajax"])
@pytest.mark.parametrize("action", ["edit", "delete"])
@pytest.mark.parametrize("first", ["reply", "author"])
def test_reply_and_author_actions_serialize(pg_editor_actors, settings, route, action, first, comments_enabled):
    _, blog = pg_editor_actors
    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
    settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 0
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    post = PostFactory(parent=blog, title="Synthetic race", slug="synthetic-race", live=True)
    model = get_model()
    parent = model.objects.create(content_object=post, site_id=settings.SITE_ID, comment="Original", is_public=True)
    author = Client()
    seed_ownership(author, parent)
    reply = Client()
    data = {
        **get_form()(post).generate_security_data(),
        "comment": "Reply",
        "parent": str(parent.pk),
        "name": "Synthetic",
        "email": "synthetic@example.com",
        "title": "Reply",
    }
    locked = threading.Event()
    attempted = threading.Event()
    release = threading.Event()
    pids = {}
    statuses = {}

    def perform(role):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                pids[role] = cursor.fetchone()[0]

            def observe(execute, sql, params, many, context):
                is_parent_lock = "FOR UPDATE" in sql and model._meta.db_table in sql
                if is_parent_lock and role != first:
                    attempted.set()
                result = execute(sql, params, many, context)
                if is_parent_lock and role == first and not locked.is_set():
                    locked.set()
                    assert release.wait(10)
                return result

            with connection.execute_wrapper(observe):
                if role == "author":
                    response = author.post(
                        reverse(f"comments-{action}-comment-ajax"),
                        {"comment_id": str(parent.pk), "comment": "Edited"},
                        **AJAX,
                    )
                else:
                    name = "comments-post-comment-ajax" if route == "ajax" else "comments-post-comment"
                    response = reply.post(reverse(name), data, **(AJAX if route == "ajax" else {}))
                statuses[role] = response.status_code
        finally:
            close_old_connections()

    second = "author" if first == "reply" else "reply"
    with ThreadPoolExecutor(max_workers=2) as pool:
        leading = pool.submit(perform, first)
        trailing = None
        try:
            assert locked.wait(10), "First operation never acquired its parent lock"
            trailing = pool.submit(perform, second)
            assert attempted.wait(10), "Competing operation omitted its parent lock"
            deadline = time.monotonic() + 5
            with connection.cursor() as cursor:
                while time.monotonic() < deadline:
                    cursor.execute("SELECT pg_blocking_pids(%s)", [pids[second]])
                    if pids[first] in cursor.fetchone()[0]:
                        break
                    assert not trailing.done(), "Competing operation completed without waiting on the parent"
                else:
                    pytest.fail("No database lock wait was observed")
        finally:
            release.set()
        leading.result(timeout=15)
        if trailing is not None:
            trailing.result(timeout=15)
    parent.refresh_from_db()
    children = model.objects.filter(parent_id=parent.pk)
    if first == "reply":
        assert statuses == {"reply": 200 if route == "ajax" else 302, "author": 403}
        assert children.count() == 1
        assert parent.comment == "Original" and parent.is_public and not parent.is_removed
    else:
        assert statuses["author"] == 200
        if action == "delete":
            assert statuses["reply"] == 400
            assert not children.exists()
            assert parent.is_removed and not parent.is_public
        else:
            assert statuses["reply"] == (200 if route == "ajax" else 302)
            assert children.count() == 1
            assert parent.comment == "Edited" and parent.is_public and not parent.is_removed
