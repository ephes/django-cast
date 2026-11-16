"""Reject ambiguous JSON before revisions or media metadata can change."""

import pytest
from django.urls import reverse
from wagtail.models import Revision


@pytest.mark.django_db
@pytest.mark.parametrize("member", ["publish", "base_revision_id", "nested"])
def test_editor_rejects_duplicate_control_members(api_client, superuser, post, member):
    api_client.force_authenticate(user=superuser)
    revision_id = post.save_revision().pk
    members = {
        "publish": '"publish":true,"publish":false',
        "base_revision_id": f'"base_revision_id":0,"base_revision_id":{revision_id}',
        "nested": '"overview":[{"type":"paragraph","value":"first","value":"second"}]',
    }
    base = "" if member == "base_revision_id" else f'"base_revision_id":{revision_id},'
    body = "{" + base + '"require_unpublished":false,"title":"Ambiguous",' + members[member] + "}"
    before = Revision.objects.count()
    response = api_client.patch(
        reverse("cast:api:editor_post_detail", args=[post.pk]), body, content_type="application/json"
    )
    assert response.status_code == 400, response.content
    assert response.json()["code"] == "validation_error"
    assert response.json()["errors"]["non_field_errors"][0]["code"] == "duplicate_member"
    assert Revision.objects.count() == before
    post.refresh_from_db()
    assert post.title != "Ambiguous"


@pytest.mark.django_db
def test_audio_metadata_rejects_duplicate_members(api_client, superuser, audio):
    api_client.force_authenticate(user=superuser)
    title = audio.title
    response = api_client.patch(
        reverse("cast:api:editor_media_audio_detail", args=[audio.pk]),
        '{"title":"First","title":"Second"}',
        content_type="application/json",
    )
    assert response.status_code == 400
    audio.refresh_from_db()
    assert audio.title == title


@pytest.mark.parametrize(
    "body,context",
    [(b"{", {}), (b"{}", {"encoding": "bz2_codec"}), (b"{}", {"encoding": "missing-codec"}), (b'{"x": NaN}', {})],
)
def test_editor_json_parser_retains_parse_errors(body, context):
    from io import BytesIO

    from rest_framework.exceptions import ParseError

    from cast.api.editor.parsers import EditorJSONParser

    with pytest.raises(ParseError):
        EditorJSONParser().parse(BytesIO(body), parser_context=context)


def test_editor_json_parser_unique_members_and_nonstrict_compatibility():
    from io import BytesIO

    from cast.api.editor.parsers import EditorJSONParser

    assert EditorJSONParser().parse(BytesIO(b'{"x": {"x": 1}, "y": [2]}')) == {"x": {"x": 1}, "y": [2]}
    parser = EditorJSONParser()
    parser.strict = False
    assert parser.parse(BytesIO(b'{"x": Infinity}'))["x"] == float("inf")
