"""Editor API Markdown convenience input for body sections."""

import sys

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from cast.models import Episode, Post
from tests.api.editor_richtext_test import assert_safe_fragment

pytestmark = pytest.mark.django_db

MARKDOWN = "## Notes\n\nSome *text* and a [link](https://example.com).\n\n```python\nprint('hi')\n```\n"
EXPECTED_BLOCKS = [
    {
        "type": "paragraph",
        "value": '<h2>Notes</h2><p>Some <i>text</i> and a <a href="https://example.com">link</a>.</p>',
    },
    {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
]


def create_url(kind):
    return reverse(f"cast:api:editor_{kind}_create")


def detail_url(kind, pk):
    return reverse(f"cast:api:editor_{kind}_detail", kwargs={"pk": pk})


@pytest.fixture(params=["post", "episode"])
def target(request, blog, podcast):
    if request.param == "post":
        return "post", blog, Post
    return "episode", podcast, Episode


def create(api_client, kind, parent, **fields):
    return api_client.post(
        create_url(kind), {"parent": {"id": parent.id}, "title": "Markdown", **fields}, format="json"
    )


def test_create_converts_markdown_into_canonical_blocks(api_client, admin_user, target):
    kind, parent, model = target
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, kind, parent, overview_markdown=MARKDOWN, detail_markdown="Detail **text**")

    assert response.status_code == 201, response.content
    data = response.json()
    assert data["overview"] == EXPECTED_BLOCKS
    assert data["detail"] == [{"type": "paragraph", "value": "<p>Detail <b>text</b></p>"}]
    assert "overview_markdown" not in data
    page = model.objects.get(id=data["id"])
    assert [block.block_type for block in page.body[0].value] == ["paragraph", "code"]


def test_markdown_and_block_list_may_be_mixed_across_sections(api_client, admin_user, blog):
    api_client.force_authenticate(user=admin_user)

    response = create(
        api_client, "post", blog, overview=[{"type": "paragraph", "value": "<p>Blocks</p>"}], detail_markdown="*md*"
    )

    assert response.status_code == 201, response.content
    assert response.json()["overview"] == [{"type": "paragraph", "value": "<p>Blocks</p>"}]
    assert response.json()["detail"] == [{"type": "paragraph", "value": "<p><i>md</i></p>"}]


def test_empty_overview_markdown_creates_empty_overview(api_client, admin_user, blog):
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, "post", blog, overview_markdown="")

    assert response.status_code == 201, response.content
    assert response.json()["overview"] == []


@pytest.mark.parametrize("section", ["overview", "detail"])
def test_create_rejects_block_list_and_markdown_for_the_same_section(api_client, admin_user, target, section):
    kind, parent, model = target
    api_client.force_authenticate(user=admin_user)
    fields = {"overview": []} if section == "detail" else {}
    fields.update({section: [], f"{section}_markdown": "Text"})

    response = create(api_client, kind, parent, **fields)

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert response.json()["errors"] == {
        f"{section}_markdown": [
            {"code": "conflict", "message": f"Send either '{section}' or '{section}_markdown', not both."}
        ]
    }
    assert not model.objects.filter(title="Markdown").exists()


def test_create_still_requires_an_overview_input(api_client, admin_user, blog):
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, "post", blog, detail_markdown="Text")

    assert response.status_code == 400
    assert response.json()["errors"] == {"overview": [{"code": "required", "message": "This field is required."}]}


@pytest.mark.parametrize("value", [None, ["list"], {"text": "x"}])
def test_markdown_must_be_a_string(api_client, admin_user, blog, value):
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, "post", blog, overview_markdown=value)

    assert response.status_code == 400
    assert list(response.json()["errors"]) == ["overview_markdown"]


@pytest.mark.parametrize(
    "markdown",
    [
        "<script>alert(1)</script>",
        '<p onclick="alert(1)">Text</p>',
        '<a href="javascript:alert(1)">x</a>',
        "[x](javascript:alert(1)) <javascript:alert(1)> [y](jav&#x61;script:alert(1))",
        "[x](data:text/html,<script>alert(1)</script>)",
        "[x](data:image/png;base64,AAAA)",
        '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
        "Text <svg onload=alert(1)>",
    ],
)
def test_embedded_html_is_escaped_and_sanitized(api_client, admin_user, blog, markdown):
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, "post", blog, overview_markdown=markdown)

    assert response.status_code == 201, response.content
    stored = Post.objects.get(id=response.json()["id"]).body.raw_data[0]["value"]
    assert len(stored) == 1
    assert stored[0]["type"] == "paragraph"
    assert_safe_fragment(stored[0]["value"])
    assert not BeautifulSoup(stored[0]["value"], "html.parser").find_all(href=True)


def test_generated_html_passes_through_the_rich_text_sanitizer(api_client, admin_user, blog):
    """Formatting outside the configured rich-text features is reduced like submitted HTML."""
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, "post", blog, overview_markdown="# Top heading\n\n## Kept heading")

    assert response.status_code == 201, response.content
    assert response.json()["overview"] == [{"type": "paragraph", "value": "<p>Top heading</p><h2>Kept heading</h2>"}]


def test_markdown_images_are_rejected(api_client, admin_user, blog):
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, "post", blog, overview_markdown="Text\n![alt](https://example.com/a.png)")

    assert response.status_code == 400
    assert response.json()["errors"] == {
        "overview_markdown": [
            {"code": "inline_image", "message": "Markdown images are not supported (lines 1-2); use image blocks."}
        ]
    }
    assert not Post.objects.filter(title="Markdown").exists()


def test_generated_block_errors_are_reported_under_the_markdown_field(api_client, admin_user, blog):
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, "post", blog, overview=[], detail_markdown="Intro\n\n```\n```\n")

    assert response.status_code == 400
    assert response.json()["errors"] == {
        "detail_markdown.1.value.source": [{"code": "required", "message": "Code block 'source' is required."}]
    }


def test_missing_markdown_dependency_is_a_validation_error(api_client, admin_user, target, monkeypatch):
    kind, parent, model = target
    monkeypatch.setitem(sys.modules, "markdown_it", None)
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, kind, parent, overview_markdown="Text")

    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    assert response.json()["errors"]["overview_markdown"][0]["code"] == "markdown_unavailable"
    assert not model.objects.filter(title="Markdown").exists()


def test_block_list_writes_do_not_need_the_markdown_dependency(api_client, admin_user, blog, monkeypatch):
    monkeypatch.setitem(sys.modules, "markdown_it", None)
    api_client.force_authenticate(user=admin_user)

    response = create(api_client, "post", blog, overview=[{"type": "paragraph", "value": "<p>Text</p>"}])

    assert response.status_code == 201, response.content


class TestMarkdownPatch:
    @pytest.fixture()
    def created(self, api_client, admin_user, target):
        kind, parent, model = target
        api_client.force_authenticate(user=admin_user)
        response = create(
            api_client,
            kind,
            parent,
            overview=[{"type": "paragraph", "value": "<p>Old overview</p>"}],
            detail=[{"type": "paragraph", "value": "<p>Old detail</p>"}],
        )
        assert response.status_code == 201, response.content
        return kind, response.json()

    def test_patch_replaces_only_the_markdown_section(self, api_client, created):
        kind, data = created

        response = api_client.patch(
            detail_url(kind, data["id"]),
            {"base_revision_id": data["latest_revision_id"], "detail_markdown": MARKDOWN},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["overview"] == [{"type": "paragraph", "value": "<p>Old overview</p>"}]
        assert response.json()["detail"] == EXPECTED_BLOCKS

    def test_patch_markdown_alone_counts_as_an_update(self, api_client, created):
        kind, data = created

        response = api_client.patch(
            detail_url(kind, data["id"]),
            {"base_revision_id": data["latest_revision_id"], "overview_markdown": ""},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["overview"] == []
        assert response.json()["latest_revision_id"] != data["latest_revision_id"]

    def test_patch_rejects_both_inputs_for_one_section(self, api_client, created):
        kind, data = created

        response = api_client.patch(
            detail_url(kind, data["id"]),
            {"base_revision_id": data["latest_revision_id"], "overview": [], "overview_markdown": "x"},
            format="json",
        )

        assert response.status_code == 400
        assert list(response.json()["errors"]) == ["overview_markdown"]

    def test_patch_markdown_error_leaves_the_draft_unchanged(self, api_client, created):
        kind, data = created

        response = api_client.patch(
            detail_url(kind, data["id"]),
            {"base_revision_id": data["latest_revision_id"], "title": "Changed", "overview_markdown": "![a](b)"},
            format="json",
        )

        assert response.status_code == 400
        current = api_client.get(detail_url(kind, data["id"])).json()
        assert current["title"] == "Markdown"
        assert current["latest_revision_id"] == data["latest_revision_id"]
