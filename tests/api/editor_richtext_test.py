"""Security and compatibility regressions for editor API rich-text writes."""

import json

import pytest
from bs4 import BeautifulSoup
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.db import OperationalError
from django.test import override_settings
from django.urls import reverse
from wagtail import blocks
from wagtail.blocks import RichTextBlock
from wagtail.documents import get_document_model
from wagtail.rich_text import RichText

from cast.api.editor.body import author_blocks_to_section
from cast.api.editor.errors import EditorValidationError
from cast.api.editor.richtext import sanitize_block_value, sanitize_rich_text
from cast.models import Post
from tests.factories import PostFactory


UNSAFE_HTML = [
    '<p>Safe</p><script>alert("cast-xss")</script>',
    '<p onclick="alert(1)">Safe</p>',
    '<img src="x" onerror="alert(1)"><p>Safe</p>',
    '<svg onload="alert(1)"><a xlink:href="javascript:alert(1)">Safe</a></svg>',
    '<iframe srcdoc="&lt;script&gt;alert(1)&lt;/script&gt;"></iframe><p>Safe</p>',
    '<p style="background:url(javascript:alert(1))">Safe</p>',
    '<p><a href="javascript:alert(1)">Safe</a></p>',
    '<p><a href="jav&#x61;script:alert(1)">Safe</a></p>',
    '<p><a href="java&#9;script:alert(1)">Safe</a></p>',
    '<p><a href="data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;">Safe</a></p>',
    '<p><a href="vbscript:msgbox(1)">Safe</a></p>',
    '<p><a href="https://example.com" onclick="alert(1)" target="_blank">Safe</a></p>',
    '<p><a linktype="unknown" href="javascript:alert(1)">Safe</a></p>',
]

MALFORMED_HTML = [
    '<p><a linktype="page" id="1&quot; onclick=&quot;alert(1)">Safe</a></p>',
    '<p><a linktype="page" id="abc">Safe</a></p>',
    '<p><a linktype="page">Safe</a></p>',
    "<math><mtext><img src=x onerror=alert(1)></mtext></math><p>Safe</p>",
    "<p><strong><em>Safe</strong> text</em></p>",
    "<li>Outside a list</li>",
]


def assert_safe_fragment(html):
    soup = BeautifulSoup(html, "html.parser")
    assert not soup.find(["script", "img", "svg", "math", "iframe", "style", "object", "embed"])
    for tag in soup.find_all(True):
        assert not any(name.startswith("on") or name in {"style", "srcdoc", "target"} for name in tag.attrs)
        href = tag.get("href", "")
        assert not any(scheme in href.lower() for scheme in ("javascript:", "vbscript:", "data:"))


@pytest.mark.parametrize("section", ["overview", "detail"])
@pytest.mark.parametrize("html", UNSAFE_HTML)
def test_paragraph_removes_active_markup_before_storage_and_rendering(section, html):
    result = author_blocks_to_section([{"type": "paragraph", "value": html}], user=None, path_prefix=section)
    stored = result[0]["value"]
    assert_safe_fragment(stored)
    assert_safe_fragment(author_blocks_to_section(result, user=None, path_prefix=section)[0]["value"])
    block = RichTextBlock()
    # Internal links in this corpus are invalid and must not reach DB resolution.
    assert_safe_fragment(str(block.render(block.to_python(stored))))


@pytest.mark.parametrize("html", MALFORMED_HTML)
def test_malformed_rich_text_is_a_field_error(html):
    with pytest.raises(EditorValidationError) as excinfo:
        author_blocks_to_section([{"type": "paragraph", "value": html}], user=None, path_prefix="detail")
    assert excinfo.value.error_map == {"detail.0.value": [{"code": "invalid", "message": "Invalid rich text."}]}


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "jav&#x61;script:alert(1)",
        "java&#9;script:alert(1)",
        "java\nscript:alert(1)",
        "data:text/html,test",
        "vbscript:msgbox(1)",
    ],
)
def test_unsafe_link_schemes_lose_href_entirely(url):
    result = author_blocks_to_section(
        [{"type": "paragraph", "value": f'<p><a href="{url}">Link</a></p>'}], user=None, path_prefix="overview"
    )
    assert not BeautifulSoup(result[0]["value"], "html.parser").find("a", href=True)


@pytest.mark.django_db
def test_sanitizer_errors_are_aggregated_with_other_block_errors(admin_user):
    with pytest.raises(EditorValidationError) as excinfo:
        author_blocks_to_section(
            [
                {"type": "image", "value": {"id": 999999}},
                {"type": "paragraph", "value": "<li>Outside a list</li>"},
                {"type": "paragraph", "value": False},
            ],
            user=admin_user,
            path_prefix="detail",
        )
    assert set(excinfo.value.error_map) == {"detail.0.value.id", "detail.1.value", "detail.2.value"}


@pytest.mark.parametrize("value", [None, "", " \n "])
def test_optional_empty_rich_text_remains_empty(value):
    block = RichTextBlock(required=False)
    assert sanitize_rich_text(block, RichText(value), path="value").source == ""


@pytest.mark.parametrize(
    "html",
    [
        "<h2>Heading</h2><h3>Subheading</h3><p><b>bold</b> <i>italic</i><br/>text &amp; more</p>",
        "<ol><li>First</li><li>Second</li></ol><ul><li>Third</li></ul>",
        '<p><a href="https://example.com/?a=1&amp;b=2">Link</a></p>',
        '<p><a href="/relative/">Relative</a> <a href="#fragment">Fragment</a></p>',
        '<p><a href="mailto:editor@example.com">Mail</a> <a href="tel:+1234">Call</a></p>',
        "<p>&lt;script&gt;literal code&lt;/script&gt;</p>",
    ],
)
def test_supported_prose_round_trips_without_random_editor_metadata(html):
    result = author_blocks_to_section([{"type": "paragraph", "value": html}], user=None, path_prefix="overview")
    assert result[0]["value"] == html
    assert author_blocks_to_section(result, user=None, path_prefix="overview") == result


def test_features_follow_editor_options_explicit_block_features_and_defaults():
    editor_settings = {
        "default": {
            "WIDGET": "wagtail.admin.rich_text.DraftailRichTextArea",
            "OPTIONS": {"features": ["blockquote", "code"]},
        }
    }
    html = "<blockquote>Quote</blockquote><p><code>inline</code> <b>plain</b></p>"
    with override_settings(WAGTAILADMIN_RICH_TEXT_EDITORS=editor_settings):
        assert sanitize_rich_text(RichTextBlock(), RichText(html), path="value").source == (
            "<blockquote>Quote</blockquote><p><code>inline</code> plain</p>"
        )
        assert author_blocks_to_section([{"type": "paragraph", "value": html}], user=None, path_prefix="overview") == [
            {"type": "paragraph", "value": "<blockquote>Quote</blockquote><p><code>inline</code> plain</p>"}
        ]
        assert sanitize_rich_text(
            RichTextBlock(features=[]), RichText("<p><b>plain</b></p>"), path="value"
        ).source == ("<p>plain</p>")
    assert (
        sanitize_rich_text(RichTextBlock(), RichText("<p><b>bold</b></p>"), path="value").source
        == "<p><b>bold</b></p>"
    )


def test_inline_embeds_do_not_fetch_providers_or_images(mocker):
    fetch = mocker.patch("wagtail.embeds.embeds.get_embed", side_effect=AssertionError("Unexpected provider request"))
    image_lookup = mocker.patch("wagtail.images.models.Image.objects.get", side_effect=AssertionError("Image lookup"))
    html = (
        '<embed embedtype="media" url="http://127.0.0.1/private"/>'
        '<embed embedtype="image" id="1" format="fullwidth" alt="Image"/><p>Safe</p>'
    )
    with pytest.raises(EditorValidationError) as excinfo:
        author_blocks_to_section([{"type": "paragraph", "value": html}], user=None, path_prefix="overview")
    assert excinfo.value.error_map == {
        "overview.0.value": [
            {"code": "inline_embed", "message": "Use structured media blocks instead of inline embeds."}
        ]
    }
    fetch.assert_not_called()
    image_lookup.assert_not_called()


@pytest.mark.parametrize("html", ['<EMBED embedtype="image" id="1">', "<embed/>", '<embed embedtype="media"/>'])
def test_inline_embed_detection_covers_case_and_void_syntax(html):
    with pytest.raises(EditorValidationError):
        author_blocks_to_section([{"type": "paragraph", "value": html}], user=None, path_prefix="overview")


def test_supplied_comment_keys_survive_and_new_random_keys_are_omitted():
    html = '<p data-block-key="comment-anchor">Existing</p><p>New</p>'
    result = author_blocks_to_section([{"type": "paragraph", "value": html}], user=None, path_prefix="overview")
    assert result[0]["value"] == html
    assert author_blocks_to_section(result, user=None, path_prefix="overview") == result
    malicious_key = '<p data-block-key="x&quot; onclick=&quot;alert(1)">Text</p>'
    result = author_blocks_to_section(
        [{"type": "paragraph", "value": malicious_key}], user=None, path_prefix="overview"
    )
    assert_safe_fragment(result[0]["value"])


def test_converter_infrastructure_failure_is_not_reported_as_bad_input(mocker):
    mocker.patch(
        "cast.api.editor.richtext.ContentstateConverter.from_database_format",
        side_effect=OperationalError("Database unavailable"),
    )
    with pytest.raises(OperationalError, match="Database unavailable"):
        sanitize_rich_text(RichTextBlock(), RichText("<p>Valid</p>"), path="overview.0.value")


def test_invalid_editor_configuration_is_not_reported_as_bad_input():
    with (
        override_settings(WAGTAILADMIN_RICH_TEXT_EDITORS={"default": {"OPTIONS": {"features": 123}}}),
        pytest.raises(ImproperlyConfigured, match="Unable to initialize"),
    ):
        sanitize_rich_text(RichTextBlock(), RichText("<p>Valid</p>"), path="overview.0.value")


def test_custom_block_wrapper_does_not_hide_invalid_rich_text_configuration():
    with (
        override_settings(
            CAST_POST_BODY_BLOCKS={"overview": ["tests.custom_post_body_blocks.weeknote_links_block"]},
            WAGTAILADMIN_RICH_TEXT_EDITORS={"default": {"OPTIONS": {"features": 123}}},
        ),
        pytest.raises(ImproperlyConfigured, match="Unable to initialize") as excinfo,
    ):
        author_blocks_to_section(
            [{"type": "weeknote_links", "value": [{"description": "<p>Valid</p>"}]}], user=None, path_prefix="overview"
        )
    assert isinstance(excinfo.value.__cause__, TypeError)


def test_invalid_native_rich_text_is_logged_and_rejected(caplog):
    with pytest.raises(EditorValidationError):
        sanitize_rich_text(RichTextBlock(), RichText(123), path="detail.0.value")
    assert "Rejected editor API rich text at detail.0.value" in caplog.text


def test_nested_custom_rich_text_retains_list_and_stream_ids():
    block = blocks.StructBlock(
        [("items", blocks.ListBlock(blocks.StreamBlock([("text", RichTextBlock()), ("label", blocks.CharBlock())])))]
    )
    list_id = "5b03012c-1c41-4819-a3eb-b16753fda527"
    stream_id = "e1cf7f41-0f9d-4f34-9f4b-07a55439306f"
    value = block.to_python(
        {
            "items": [
                {
                    "type": "item",
                    "id": list_id,
                    "value": [
                        {"type": "text", "id": stream_id, "value": '<p onclick="alert(1)">Safe</p>'},
                    ],
                }
            ]
        }
    )
    cleaned = sanitize_block_value(block, value, path="detail.0.value")
    stored = block.get_prep_value(block.clean(cleaned))["items"][0]
    assert stored["id"] == list_id
    assert stored["value"][0] == {"type": "text", "id": stream_id, "value": "<p>Safe</p>"}


def test_raw_html_custom_blocks_are_rejected_at_the_nested_path():
    block = blocks.StructBlock([("raw", blocks.RawHTMLBlock())])
    with pytest.raises(EditorValidationError) as excinfo:
        sanitize_block_value(block, block.to_python({"raw": "<script>alert(1)</script>"}), path="detail.0.value")
    assert "detail.0.value.raw" in excinfo.value.error_map


@pytest.mark.django_db
def test_internal_page_and_document_links_survive_conversion_and_rendering(blog):
    document = get_document_model().objects.create(title="Notes", file=ContentFile(b"Notes", name="notes.txt"))
    html = f'<p><a linktype="page" id="{blog.pk}">Blog</a> <a linktype="document" id="{document.pk}">Notes</a></p>'
    result = author_blocks_to_section([{"type": "paragraph", "value": html}], user=None, path_prefix="overview")
    assert result[0]["value"] == html
    block = RichTextBlock()
    rendered = str(block.render(block.to_python(result[0]["value"])))
    assert "href=" in rendered
    assert "linktype=" not in rendered
    assert "Blog</a>" in rendered
    assert "Notes</a>" in rendered


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["post", "episode"])
def test_deleted_page_and_document_links_survive_api_writes(api_client, blog, podcast, admin_user, kind):
    target = PostFactory(parent=blog, title="Deleted target", slug="deleted-target")
    document = get_document_model().objects.create(
        title="Deleted notes", file=ContentFile(b"Notes", name="deleted.txt")
    )
    page_id, document_id = target.pk, document.pk
    target.delete()
    document.delete()
    html = (
        f'<p><a linktype="page" id="{page_id}">Deleted page</a> '
        f'<a linktype="document" id="{document_id}">Deleted document</a></p>'
    )
    body = [{"type": "paragraph", "value": html}]
    api_client.force_authenticate(user=admin_user)
    parent = blog if kind == "post" else podcast
    response = api_client.post(
        reverse(f"cast:api:editor_{kind}_create"),
        {"parent": {"id": parent.pk}, "title": "Broken links", "overview": body, "detail": body},
        format="json",
    )
    assert response.status_code == 201, response.content
    created = response.json()
    assert created["overview"] == body
    assert created["detail"] == body
    response = api_client.patch(
        reverse(f"cast:api:editor_{kind}_detail", kwargs={"pk": created["id"]}),
        {"base_revision_id": created["latest_revision_id"], "overview": body, "detail": body},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["overview"] == body
    assert response.json()["detail"] == body
    preview = api_client.get(reverse(f"cast:api:editor_{kind}_preview", kwargs={"pk": created["id"]}))
    assert preview.status_code == 200, preview.content
    assert "Deleted page" in preview.content.decode()
    assert "Deleted document" in preview.content.decode()


@pytest.mark.django_db
def test_resubmitting_existing_inline_media_is_rejected_without_data_loss(api_client, blog, admin_user):
    html = '<embed embedtype="image" id="999999" format="fullwidth" alt="Existing image"/>'
    post = PostFactory(
        parent=blog,
        owner=admin_user,
        title="Existing inline media",
        slug="existing-inline-media",
        body=json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": html}]}]),
    )
    post.save_revision(user=admin_user)
    api_client.force_authenticate(user=admin_user)
    detail_url = reverse("cast:api:editor_post_detail", kwargs={"pk": post.pk})
    original = api_client.get(detail_url).json()
    revision_count = post.revisions.count()
    response = api_client.patch(
        detail_url,
        {"base_revision_id": original["latest_revision_id"], "overview": original["overview"]},
        format="json",
    )
    assert response.status_code == 400, response.content
    assert response.json()["errors"] == {
        "overview.0.value": [
            {"code": "inline_embed", "message": "Use structured media blocks instead of inline embeds."}
        ]
    }
    assert post.revisions.count() == revision_count
    assert api_client.get(detail_url).json()["overview"] == original["overview"]
    # Omitted sections retain their historical contents, as the write-time contract promises.
    response = api_client.patch(
        detail_url, {"base_revision_id": original["latest_revision_id"], "title": "Metadata only"}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["overview"] == original["overview"]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["post", "episode"])
def test_malformed_create_and_patch_return_400_without_saving(api_client, blog, podcast, admin_user, kind):
    api_client.force_authenticate(user=admin_user)
    parent = blog if kind == "post" else podcast
    create_url = reverse(f"cast:api:editor_{kind}_create")
    body = [{"type": "paragraph", "value": '<p><a linktype="page" id="abc">Invalid</a></p>'}]
    payload = {"parent": {"id": parent.id}, "title": "Bad rich text", "overview": body}
    count = Post.objects.count()
    response = api_client.post(create_url, payload, format="json")
    assert response.status_code == 400
    assert response.json() == {
        "code": "validation_error",
        "errors": {"overview.0.value": [{"code": "invalid", "message": "Invalid rich text."}]},
    }
    assert Post.objects.count() == count
    created = api_client.post(create_url, {**payload, "overview": []}, format="json").json()
    page = Post.objects.get(pk=created["id"])
    revision_count = page.revisions.count()
    response = api_client.patch(
        reverse(f"cast:api:editor_{kind}_detail", kwargs={"pk": page.pk}),
        {"base_revision_id": created["latest_revision_id"], "detail": body},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["errors"] == {"detail.0.value": [{"code": "invalid", "message": "Invalid rich text."}]}
    assert page.revisions.count() == revision_count


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["post", "episode"])
def test_create_patch_revision_and_preview_sanitize_both_sections(api_client, blog, podcast, admin_user, kind):
    api_client.force_authenticate(user=admin_user)
    parent = blog if kind == "post" else podcast
    unsafe = '<p onclick="alert(1)">Safe content</p><script>alert("cast-xss")</script>'
    body = [{"type": "paragraph", "value": unsafe}]
    response = api_client.post(
        reverse(f"cast:api:editor_{kind}_create"),
        {"parent": {"id": parent.id}, "title": "Safe rich text", "overview": body, "detail": body},
        format="json",
    )
    assert response.status_code == 201, response.content
    created = response.json()
    detail_url = reverse(f"cast:api:editor_{kind}_detail", kwargs={"pk": created["id"]})
    preview_url = reverse(f"cast:api:editor_{kind}_preview", kwargs={"pk": created["id"]})
    for operation in ("create", "patch"):
        if operation == "patch":
            response = api_client.patch(
                detail_url,
                {"base_revision_id": created["latest_revision_id"], "overview": body, "detail": body},
                format="json",
            )
            assert response.status_code == 200, response.content
        data = response.json()
        for section in ("overview", "detail"):
            assert_safe_fragment(data[section][0]["value"])
        page = Post.objects.get(pk=created["id"]).specific
        revision = page.get_latest_revision_as_object()
        for section in revision.body:
            assert_safe_fragment(section.value[0].value.source)
        assert api_client.get(detail_url).json()["overview"] == data["overview"]
        preview = api_client.get(preview_url)
        assert preview.status_code == 200, preview.content
        assert "Safe content" in preview.content.decode()
        assert 'onclick="alert(1)"' not in preview.content.decode()
        assert '<script>alert("cast-xss")</script>' not in preview.content.decode()
    if kind == "post":
        published = api_client.post(
            reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]}), {}, format="json"
        )
        assert published.status_code == 200, published.content
        api_client.force_authenticate(user=None)
        public = api_client.get(published.json()["public_url"])
        assert public.status_code == 200, public.content
        assert "Safe content" in public.content.decode()
        assert 'onclick="alert(1)"' not in public.content.decode()
        assert '<script>alert("cast-xss")</script>' not in public.content.decode()
