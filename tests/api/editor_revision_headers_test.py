"""Revision header admission uses the same bounded integer decoder as the body."""

import pytest
from django.urls import reverse
from rest_framework import serializers

from tests.factories import EpisodeFactory, PostFactory


@pytest.fixture(params=["post", "episode"])
def revision_target(request, blog, podcast, admin_user):
    kind = request.param
    factory, parent = (PostFactory, blog) if kind == "post" else (EpisodeFactory, podcast)
    page = factory(parent=parent, title="Synthetic draft", slug="synthetic-draft", live=False)
    page.save_revision(user=admin_user)
    return kind, page


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["patch", "publish"])
@pytest.mark.parametrize("digits", ["9" * 5000, "0" * 1001])
def test_oversized_revision_header_is_validation_error(api_client, admin_user, revision_target, operation, digits):
    kind, page = revision_target
    before = page.revisions.count()
    revision_id = page.latest_revision_id
    url = reverse(f"cast:api:editor_{kind}_{'detail' if operation == 'patch' else 'publish'}", args=[page.pk])
    api_client.force_authenticate(user=admin_user)
    send = api_client.patch if operation == "patch" else api_client.post
    response = send(url, {"title": "Rejected"}, format="json", HTTP_IF_MATCH=f'"{digits}"')
    assert response.status_code == 400, response.content
    assert response.json() == {
        "code": "validation_error",
        "errors": {
            "If-Match": [{"code": "invalid", "message": 'If-Match must be a quoted revision id such as "123".'}]
        },
    }
    page.refresh_from_db()
    assert page.latest_revision_id == revision_id
    assert page.revisions.count() == before
    assert not page.live


@pytest.mark.django_db
@pytest.mark.parametrize("digits", ["0", "9" * serializers.IntegerField.MAX_STRING_LENGTH])
def test_boundary_revision_header_remains_a_conflict(api_client, admin_user, revision_target, digits):
    kind, page = revision_target
    api_client.force_authenticate(user=admin_user)
    response = api_client.patch(
        reverse(f"cast:api:editor_{kind}_detail", args=[page.pk]),
        {"title": "Rejected"},
        format="json",
        HTTP_IF_MATCH=f'"{digits}"',
    )
    assert response.status_code == 409, response.content
    assert response.json()["submitted_base_revision_id"] == int(digits)
