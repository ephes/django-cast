import json
from uuid import uuid4

import pytest
from django.urls import reverse
from wagtail import blocks
from wagtail.models import Comment

from cast.content.blocks import GenericBlockConverter, content_converters
from cast.models import Post
from tests.factories import PostFactory


@pytest.mark.django_db
def test_author_roundtrip_retains_real_streamfield_comment_anchors(api_client, blog, admin_user):
    section_id, paragraph_id, opaque_id, code_id = [str(uuid4()) for _ in range(4)]
    original = [
        {"id": paragraph_id, "type": "paragraph", "value": '<p data-block-key="anchor">Synthetic example</p>'},
        {"id": opaque_id, "type": "embed", "value": "https://example.com/"},
        {"id": code_id, "type": "code", "value": {"language": "python", "source": "pass"}},
    ]
    page = PostFactory(
        parent=blog,
        title="Identity example",
        slug="identity-example",
        owner=admin_user,
        live=False,
        body=json.dumps([{"id": section_id, "type": "overview", "value": original}]),
    )
    comment = Comment.objects.create(
        page=page,
        user=admin_user,
        text="Synthetic comment",
        contentpath=f"body.{section_id}.{paragraph_id}",
        position='{"blockKey":"anchor"}',
    )
    page.save_revision(user=admin_user)
    api_client.force_authenticate(user=admin_user)
    url = reverse("cast:api:editor_post_detail", args=[page.pk])
    before = api_client.get(url).json()
    assert before["overview"][0]["existing_block_id"] == paragraph_id
    for order in (before["overview"], before["overview"][::-1]):
        response = api_client.patch(
            url, {"base_revision_id": before["latest_revision_id"], "overview": order}, format="json"
        )
        assert response.status_code == 200, response.content
        before = api_client.get(url).json()
        draft = Post.objects.get(pk=page.pk).get_latest_revision_as_object()
        stored = draft.body.raw_data[0]
        assert stored["id"] == section_id
        assert {block["id"] for block in stored["value"]} == {paragraph_id, opaque_id, code_id}
        assert comment.has_valid_contentpath(draft)
        assert draft.wagtail_admin_comments.get(id=comment.pk).position == comment.position
        assert before["overview"] == order
    # A block identity from overview cannot be attached to a new detail block.
    response = api_client.patch(
        url, {"base_revision_id": before["latest_revision_id"], "detail": [before["overview"][-1]]}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_unbounded_custom_read_keeps_opaque_source(api_client, blog, admin_user, monkeypatch):
    source = {"language": "python", "source": "pass"}
    page = PostFactory(
        parent=blog,
        title="Custom example",
        slug="custom-example",
        owner=admin_user,
        live=False,
        body=json.dumps([{"type": "overview", "value": [{"type": "code", "value": source}]}]),
    )
    revision = page.save_revision(user=admin_user)
    revision.refresh_from_db()
    before = revision.content

    class CyclicBlock(blocks.Block):
        def get_prep_value(self, value):
            result = []
            result.append(result)
            return result

    converters = content_converters("overview")
    converters["code"] = GenericBlockConverter("code", CyclicBlock())
    monkeypatch.setattr("cast.content.convert.content_converters", lambda section: converters)
    api_client.force_authenticate(user=admin_user)
    response = api_client.get(reverse("cast:api:editor_post_detail", args=[page.pk]))
    assert response.status_code == 200
    assert response.json()["overview"] == [
        {"type": "unsupported", "value": {"stored_type": "code", "position": "overview.0"}}
    ]
    revision.refresh_from_db()
    assert revision.content == before
