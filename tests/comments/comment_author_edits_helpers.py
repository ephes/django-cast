"""Shared test data and setup helpers."""

from cast.comments import author_edits


def seed_ownership(client, comment):
    session = client.session
    session[author_edits.SESSION_KEY] = [str(comment.pk)]
    session.save()


AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
