import subprocess
import sys

import pytest
from django.test import override_settings
from django.template.loader import render_to_string
from wagtail import blocks
from wagtail.blocks import StreamValue
from wagtail.blocks.definition_lookup import BlockDefinitionLookup

from cast.models import Blog
from cast.models.pages import ContentBlock, HtmlField, Post
from cast.models.repository import PostDetailContext
from cast.post_body_blocks import configured_content_blocks, default_content_blocks
from tests.factories import PostFactory


DEFAULT_BLOCK_NAMES = [
    "heading",
    "paragraph",
    "code",
    "image",
    "gallery",
    "embed",
    "video",
    "audio",
]


def _custom_body_stream_value(raw_body):
    body_block = blocks.StreamBlock(
        [
            ("overview", ContentBlock(section="overview")),
            ("detail", ContentBlock(section="detail")),
        ]
    )
    return StreamValue(body_block, raw_body, is_lazy=True)


def _repository_for_post(post: Post, blog: Blog) -> PostDetailContext:
    return PostDetailContext(
        post_id=post.pk,
        template_base_dir="bootstrap4",
        blog=blog,
        root_nav_links=[],
        comments_are_enabled=False,
        has_audio=False,
        page_url="/custom-post/",
        absolute_page_url="http://testserver/custom-post/",
        owner_username=blog.owner.username,
        blog_url="/blog/",
        cover_image_url="",
        cover_alt_text="",
        audio_by_id={},
        video_by_id={},
        image_by_id={},
        renditions_for_posts={},
    )


def test_default_content_blocks_match_existing_body_blocks(settings):
    settings.CAST_POST_BODY_BLOCKS = None

    overview = ContentBlock(section="overview")
    detail = ContentBlock(section="detail")

    assert list(overview.child_blocks) == DEFAULT_BLOCK_NAMES
    assert list(detail.child_blocks) == DEFAULT_BLOCK_NAMES
    assert [name for name, _block in default_content_blocks()] == DEFAULT_BLOCK_NAMES


@pytest.mark.parametrize(
    "section,path,expected_section,unexpected_section",
    [
        ("detail", "tests.custom_post_body_blocks.detail_callout_block", "detail", "overview"),
        ("overview", "tests.custom_post_body_blocks.overview_callout_block", "overview", "detail"),
    ],
)
def test_configured_blocks_are_appended_only_to_their_section(section, path, expected_section, unexpected_section):
    with override_settings(CAST_POST_BODY_BLOCKS={section: [path]}):
        expected_block = ContentBlock(section=expected_section)
        unexpected_block = ContentBlock(section=unexpected_section)

    assert list(expected_block.child_blocks) == [*DEFAULT_BLOCK_NAMES, f"{section}_callout"]
    assert list(unexpected_block.child_blocks) == DEFAULT_BLOCK_NAMES


def test_invalid_configured_blocks_fall_back_to_defaults():
    with override_settings(CAST_POST_BODY_BLOCKS="not-a-dict"):
        assert configured_content_blocks("detail") == []

    with override_settings(CAST_POST_BODY_BLOCKS={"detail": ["tests.custom_post_body_blocks.invalid_shape_block"]}):
        assert configured_content_blocks("detail") == []
        assert list(ContentBlock(section="detail").child_blocks) == DEFAULT_BLOCK_NAMES
        assert configured_content_blocks("not-a-section") == []


def test_content_block_deconstruct_round_trips_section():
    block = ContentBlock(section="detail")

    assert block.deconstruct() == ("cast.models.pages.ContentBlock", [], {"section": "detail"})
    assert block.deconstruct_with_lookup(object()) == ("cast.models.pages.ContentBlock", [], {"section": "detail"})

    path, args, kwargs = block.deconstruct()
    reconstructed = ContentBlock(*args, **kwargs)

    assert path == "cast.models.pages.ContentBlock"
    assert reconstructed.section == "detail"


def test_content_block_constructs_from_wagtail_block_lookup():
    lookup = BlockDefinitionLookup({0: ("cast.models.pages.ContentBlock", [], {"section": "overview"})})

    block = lookup.get_block(0)

    assert isinstance(block, ContentBlock)
    assert block.section == "overview"


@pytest.mark.django_db
@override_settings(
    CAST_POST_BODY_BLOCKS={
        "overview": ["tests.custom_post_body_blocks.overview_callout_block"],
        "detail": ["tests.custom_post_body_blocks.detail_callout_block"],
    }
)
def test_custom_block_renders_through_detail_page_and_description(rf, blog):
    post = PostFactory(
        owner=blog.owner,
        parent=blog,
        title="Custom body post",
        slug="custom-body-post",
        body="[]",
    )
    post.body = _custom_body_stream_value(
        [
            {"type": "overview", "value": [{"type": "overview_callout", "value": "Overview custom block"}]},
            {"type": "detail", "value": [{"type": "detail_callout", "value": "Detail custom block"}]},
        ]
    )
    repository = _repository_for_post(post, blog)
    request = rf.get("/custom-post/")
    request.htmx = False

    detail_html = post.serve(request, repository=repository).render().content.decode()
    index_html = render_to_string(
        "cast/bootstrap4/post_body.html",
        {
            "page": post,
            "render_detail": False,
            "render_for_feed": False,
            "comments_are_enabled": False,
        },
    )
    preview_html = render_to_string(
        "cast/bootstrap4/post_body.html",
        {
            "page": post,
            "render_detail": True,
            "render_for_feed": False,
            "comments_are_enabled": False,
            "is_preview": True,
        },
    )
    overview_description = post.get_description(
        request=request,
        repository=repository,
        render_detail=False,
        escape_html=False,
        remove_newlines=False,
    )
    detail_description = post.get_description(
        request=request,
        repository=repository,
        render_detail=True,
        escape_html=False,
        remove_newlines=False,
    )
    html_overview_field = HtmlField(source="*", render_detail=False)
    html_overview_field._context = {"request": request}
    html_detail_field = HtmlField(source="*", render_detail=True)
    html_detail_field._context = {"request": request}
    html_overview = html_overview_field.to_representation(post)
    html_detail = html_detail_field.to_representation(post)

    assert "Overview custom block" in detail_html
    assert "Detail custom block" in detail_html
    assert "Overview custom block" in index_html
    assert "Detail custom block" not in index_html
    assert "Detail custom block" in preview_html
    assert "Overview custom block" in overview_description
    assert "Detail custom block" not in overview_description
    assert "Detail custom block" in detail_description
    assert "Overview custom block" in html_overview
    assert "Detail custom block" not in html_overview
    assert "Detail custom block" in html_detail


def test_repository_serialization_round_trips_custom_block_with_importable_setting():
    code = """
import json
import django

django.setup()

from cast.models import Post
from cast.models.repository import deserialize_post, serialize_post

field = Post._meta.get_field("body")
assert "detail_callout" in field.stream_block.child_blocks["detail"].child_blocks

raw_body = [
    {"type": "detail", "value": [{"type": "detail_callout", "value": "round trip custom block"}]},
]
post = Post(
    id=1,
    pk=1,
    title="Round trip",
    slug="round-trip",
    body=json.dumps(raw_body),
)
data = serialize_post(post)
reconstructed = deserialize_post(data)
inner_block = list(list(reconstructed.body)[0].value)[0]

assert json.loads(serialize_post(reconstructed)["body"]) == raw_body
assert inner_block.block_type == "detail_callout"
assert str(inner_block) == "round trip custom block"
"""

    result = subprocess.run(
        [sys.executable, "-m", "django", "shell", "--settings=tests.post_body_blocks_settings", "-c", code],
        cwd=".",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_makemigrations_check_has_no_churn_with_non_empty_custom_block_setting():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "django",
            "makemigrations",
            "cast",
            "--check",
            "--dry-run",
            "--settings=tests.post_body_blocks_settings",
        ],
        cwd=".",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "No changes detected in app 'cast'" in result.stdout
    assert "tests.custom_post_body_blocks" not in result.stdout
    assert "tests.custom_post_body_blocks" not in result.stderr
