"""Shared test data and setup helpers."""

import itertools

import django_comments
from django.urls import reverse

_addresses = (f"198.51.100.{n}" for n in itertools.count(1))


_texts = (f"new content {n}" for n in itertools.count(1))


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
