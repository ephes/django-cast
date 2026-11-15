"""Shared test data and setup helpers."""

from django.urls import reverse
from django_comments import get_form


def comment_payload(target, preview):
    form = get_form()(target)
    data = {name: str(form[name].value()) for name in ("content_type", "object_pk", "timestamp", "security_hash")}
    data.update(comment="Still allowed?", name="Visitor", email="visitor@example.com", title="Comment")
    if preview:
        data["preview"] = "1"
    return data


def submit(client, endpoint, data):
    return client.post(reverse(endpoint), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
