"""Media references must be admitted before binding SQL or saving a revision."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from wagtail.images import get_image_model
from wagtail.models import Page, Revision

from cast.content.media_refs import MediaResolution, get_choosable_audio, get_choosable_image, get_choosable_video
from cast.models import Audio, Post, Video


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["image", "gallery", "audio", "video"])
@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize("object_id", [-(10**100), 10**100, -(2**63) - 1, 2**63, -(2**63), 2**63 - 1, True, False])
def test_media_id_domain_returns_field_errors_without_mutation(
    api_client, admin_user, blog, post, kind, method, object_id
):
    api_client.force_authenticate(user=admin_user)
    ref = {"id": object_id}
    payload = {"overview": [{"type": kind, "value": [ref] if kind == "gallery" else ref}]}
    if method == "post":
        payload.update(parent={"id": blog.pk}, title="Synthetic invalid media")
        url = reverse("cast:api:editor_post_create")
    else:
        payload["base_revision_id"] = post.save_revision().pk
        url = reverse("cast:api:editor_post_detail", args=[post.pk])
    before = list(Page.objects.values()), list(Post.objects.values()), list(Revision.objects.values())

    response = getattr(api_client, method)(url, payload, format="json")

    assert response.status_code == 400, response.content
    assert response.json()["code"] == "validation_error"
    path = "overview.0.value.0.id" if kind == "gallery" else "overview.0.value.id"
    assert response.json()["errors"][path][0]["code"] == "not_found"
    assert (list(Page.objects.values()), list(Post.objects.values()), list(Revision.objects.values())) == before


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "model", "resolve"),
    [
        ("image", get_image_model(), get_choosable_image),
        ("audio", Audio, get_choosable_audio),
        ("video", Video, get_choosable_video),
    ],
)
def test_media_model_integer_boundaries_precede_all_resolution_queries(admin_user, kind, model, resolve):
    lower, upper = connection.ops.integer_field_range(model._meta.pk.get_internal_type())
    for object_id in (lower - 1, upper + 1, -(10**100), 10**100):
        with CaptureQueriesContext(connection) as queries:
            assert resolve(object_id, admin_user) is None
            resolution = MediaResolution(admin_user)
            resolution.prefetch([{"type": kind, "value": {"id": object_id}}], stored=False)
            assert resolution.resolve(kind, object_id) is None
            resolution.prefetch([{"type": kind, "value": object_id}], stored=True)
        assert len(queries) == 0
    # Representable, nonexistent IDs still follow normal unavailable resolution.
    for object_id in (lower, upper):
        assert resolve(object_id, admin_user) is None
        assert MediaResolution(admin_user).resolve(kind, object_id) is None
