# Post.body StreamField Block Extension Point

## Summary

Add a supported extension point that lets projects append custom Wagtail blocks to
the existing `Post.body` StreamField sections. The extension should preserve the
current django-cast `Post` and `Episode` models, the two-section `overview` /
`detail` body structure, and the existing render paths for detail pages, list
previews, feeds, API HTML fields, previews, and repository cache round-trips.

Recommendation: accept the feature in a small first slice. The shape is useful
and fits django-cast because downstream projects already benefit from the shared
post/feed/rendering pipeline, and custom structured content should not require a
fork or an `apps.ready()` mutation of `Post._meta.get_field("body").stream_block`.

## Problem

`cast.models.pages.Post.body` currently has two top-level sections:

- `overview`
- `detail`

Both sections use `ContentBlock`, which has a fixed child block set:

- `heading`
- `paragraph`
- `code`
- `image`
- `gallery`
- `embed`
- `video`
- `audio`

That default set works for generic blog and podcast content. Some consumer sites
need structured project-specific content that still belongs inside the normal
body flow. For example, Django Chat show notes could use a structured
`show_note_section` block instead of encoding "Links", "Projects", "Books",
"YouTube", or "Sponsor" as emoji-prefixed headings.

The desired behavior is editorially explicit: editors choose a structured block
in Wagtail, and django-cast renders that block through the normal body rendering
paths. This is not a content transformation or an emoji migration feature.

## Goals

- Let projects append custom blocks independently for `overview` and `detail`.
- Build the configured blocks as part of the real `StreamField` / block
  definition, before Wagtail admin forms, serializers, and renderers use it.
- Keep default django-cast blocks available and unchanged by default.
- Avoid runtime monkeypatching in `apps.ready()`.
- Keep project-specific blocks working through existing page, feed, preview, API,
  and repository serialization paths.
- Provide validation and tests for invalid settings, duplicate names, and
  migration/deconstruction behavior.
- Document the supported extension API and replace the current docs guidance
  that implies editing `ContentBlock` directly.

## Non-Goals

- Do not add Django Chat's show-note block to django-cast itself.
- Do not migrate or rewrite existing emoji-based headings.
- Do not let projects replace, remove, or reorder django-cast's default blocks in
  the first slice.
- Do not add per-blog, per-podcast, per-request, or per-theme block registries.
- Do not add a generalized media extraction API for custom blocks in the first
  slice.
- Do not guarantee that clients consuming raw Wagtail API body JSON can render
  arbitrary custom blocks without project-specific client support.

## Proposed API

Use `CAST_POST_BODY_BLOCKS`, a Django setting that maps body section names to
lists of dotted factory paths. The `POST` qualifier is intentional: this setting
extends the `Post.body` field, which is also inherited by `Episode`, and avoids a
broader name that could be confused with other StreamField bodies later.

```python
CAST_POST_BODY_BLOCKS = {
    "overview": [],
    "detail": [
        "django_chat.blocks.show_note_section_block",
    ],
}
```

Each factory returns a `(name, block)` tuple:

```python
from wagtail import blocks


class ShowNoteSectionBlock(blocks.StructBlock):
    icon = blocks.ChoiceBlock(
        choices=[
            ("links", "Links"),
            ("projects", "Projects"),
            ("books", "Books"),
            ("youtube", "YouTube"),
            ("sponsor", "Sponsor"),
        ]
    )
    heading = blocks.CharBlock()
    body = blocks.RichTextBlock(required=False)

    class Meta:
        icon = "list-ul"
        template = "django_chat/blocks/show_note_section.html"


def show_note_section_block():
    return ("show_note_section", ShowNoteSectionBlock())
```

First-slice behavior:

- Recognize only `overview` and `detail` as section keys.
- Append configured blocks after the default django-cast blocks.
- Reject names that collide with built-in block names.
- Reject duplicate custom block names within the same section.
- Resolve dotted paths with `django.utils.module_loading.import_string`.
- Require each factory to return a two-item tuple of `(str, wagtail.blocks.Block)`.
- Treat a missing setting the same as `{"overview": [], "detail": []}`.

## Implementation Outline

Move the built-in child block definitions into a helper that returns fresh block
instances:

```python
def default_content_blocks():
    return [
        ("heading", blocks.CharBlock(classname="full title")),
        ("paragraph", blocks.RichTextBlock()),
        ("code", CodeBlock(icon="code")),
        ("image", CastImageChooserBlock(template="cast/image/image.html")),
        ("gallery", GalleryBlockWithLayout()),
        ("embed", EmbedBlock()),
        ("video", VideoChooserBlock(template="cast/video/video.html", icon="media")),
        ("audio", AudioChooserBlock(template="cast/audio/audio.html", icon="media")),
    ]
```

Add a configured-block loader:

```python
def configured_content_blocks(section: str):
    ...
```

Change `ContentBlock` to accept its section and to deconstruct back to the
`ContentBlock` subclass instead of Wagtail's default `StreamBlock`
deconstruction:

```python
class ContentBlock(blocks.StreamBlock):
    def __init__(self, *, section: str, **kwargs):
        self.section = section
        super().__init__(
            default_content_blocks() + configured_content_blocks(section),
            **kwargs,
        )

    def deconstruct(self):
        return ("cast.models.pages.ContentBlock", [], {"section": self.section})

    def deconstruct_with_lookup(self, lookup):
        return self.deconstruct()

    class Meta:
        icon = "form"
```

Do not call `super().deconstruct()` here. Wagtail deliberately deconstructs
`StreamBlock` subclasses as plain `wagtail.blocks.StreamBlock` instances with the
full resolved child block list frozen into migrations. That default is wrong for
this extension point because consumer settings would then be serialized into
field migrations. django-cast should treat the block list as code/settings-owned
runtime configuration, with `section` as the only migration-stable constructor
argument. On Wagtail versions that use `BlockDefinitionLookupBuilder`,
`StreamField` migration serialization calls `deconstruct_with_lookup()` rather
than the block's plain `deconstruct()`, so both methods must return the stable
`ContentBlock(section=...)` definition.

Change `Post.body` to pass the section explicitly:

```python
body = StreamField(
    [
        ("overview", ContentBlock(section="overview")),
        ("detail", ContentBlock(section="detail")),
    ],
    use_json_field=True,
)
```

## Migration Requirements

This feature changes runtime block definitions but not the database schema.
Migration behavior is still important because Wagtail block definitions are part
of Django field deconstruction.

Requirements:

- `makemigrations --check` must pass with the default empty setting.
- A consumer project with a non-empty `CAST_POST_BODY_BLOCKS` setting must be
  able to run `makemigrations --check` without Django detecting changes for the
  `cast` app. This is a hard acceptance test for the deconstruction strategy.
- If django-cast needs an `AlterField` migration to move from the fully serialized
  block tree to `ContentBlock(section=...)`, that migration should be generated
  under default settings and reviewed to avoid embedding downstream block paths.
- The setting is a runtime/content contract: removing a configured block after
  content has been saved with that block may make existing content uneditable or
  unrenderable until the content is migrated or the block is restored.

## Rendering Behavior

The current theme templates are mostly compatible with this extension because
they iterate the body sections and call Wagtail's block rendering generically.
The Bootstrap 5 theme wraps inner blocks with `block-{{ block.block_type }}`;
the Vue and Python Podcast templates include body sections generically.

Expected behavior:

- Wagtail admin exposes configured blocks in the matching `overview` or `detail`
  section.
- Public detail pages render custom blocks through `{% include_block block %}`.
- Index/list pages render custom blocks only when they appear in visible
  `overview` content.
- Feed descriptions render custom blocks through `Post.get_description()`.
- `html_overview` and `html_detail` API fields render custom blocks through the
  same HTML path.
- Raw Wagtail API body JSON includes the custom block type and value using
  Wagtail's normal serialization.
- Repository cache serialization continues to store `post.body.raw_data` and
  reconstruct posts in an environment where the same block setting is importable.

Custom block templates should be written to handle the contexts where django-cast
already renders body content, especially feed rendering (`render_for_feed=True`)
and preview rendering.

## Media Sync Behavior

The first slice should not try to introspect custom blocks for media references.
The existing `Post.sync_media_ids()` path should continue to handle django-cast's
built-in `image`, `gallery`, `video`, and `audio` blocks only.

Implications:

- A custom block can render its own chooser values if Wagtail can serialize and
  render them normally.
- A custom block's media references will not automatically update the existing
  `Post.images`, `Post.galleries`, `Post.videos`, or `Post.audios` relationships.
- A later extension can add an explicit media extractor hook if a real custom
  block needs repository-level media prefetch/rendition support.

## Validation And System Checks

Add validation close to the loader and expose deployment-time feedback through
django-cast system checks.

Checks should cover:

- `CAST_POST_BODY_BLOCKS` is a dict when configured.
- Only `overview` and `detail` keys are present.
- Values are lists or tuples of dotted import paths.
- Each path imports successfully.
- Each imported object is callable.
- Each factory returns `(name, block)`.
- Names are non-empty strings.
- Blocks are Wagtail `Block` instances.
- Names do not collide with built-in block names.
- No duplicate configured names exist within a section.

## Tests

Add focused tests for:

- Default `Post.body` block definitions are unchanged when the setting is absent.
- A configured detail-only block appears under `detail` and not `overview`.
- A configured overview-only block appears under `overview` and not `detail`.
- Duplicate or colliding names fail with a clear error/check message.
- Invalid setting shapes fail with clear error/check messages.
- `ContentBlock(section=...)` deconstructs and reconstructs with the section
  through both `deconstruct()` and `deconstruct_with_lookup()`.
- `makemigrations --check` or an equivalent migration-state test does not detect
  consumer-specific block churn when `CAST_POST_BODY_BLOCKS` is non-empty.
- A sample custom block renders through page/detail rendering and
  `Post.get_description()`.
- Repository serialization/cache reconstruction can round-trip a post containing
  a configured custom block when the same setting is active.

## Documentation

Update:

- `docs/content/streamfield.rst`
- `docs/content/blogs-and-posts.rst`
- `docs/reference/models.rst`, if it documents the body structure in detail
- Current release notes when implemented

The StreamField docs currently show adding a custom block by editing
`ContentBlock` directly. Replace that with the supported setting/factory API and
include warnings about stable block names, templates, feed-safe rendering, and
the limits of first-slice media sync.

## Sibling Repo Impact

Checked template usage in:

- `../cast-bootstrap5`
- `../cast-vue`
- `../homepage`
- `../python-podcast`

No template API change is required for the first slice because templates render
body sections/blocks generically. Consumer projects that add custom blocks must
provide templates and client-side rendering support where they have custom API
clients.

## Open Questions

- Should direct callable objects be supported in addition to dotted paths, or
  should the first slice require dotted paths for settings portability?
- Should django-cast eventually expose a media extractor hook for custom blocks
  that need repository-level media/rendition prefetching?
- Should custom blocks be allowed to opt into only `Post`, only `Episode`, or
  both? The first slice should apply to both because `Episode` inherits
  `Post.body`.

## Success Criteria

- Projects can add a custom `detail` block without forking django-cast.
- Existing projects with no setting see the same default body blocks.
- Custom blocks are visible and editable in Wagtail admin.
- Custom blocks render through detail pages, feed descriptions, API HTML fields,
  previews, and cached repository reconstruction.
- Invalid configuration fails early with actionable messages.
- No `apps.ready()` monkeypatching is needed.
- Documentation and release notes describe the supported extension point and its
  first-slice limits.
