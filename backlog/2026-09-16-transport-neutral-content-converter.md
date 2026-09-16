# Transport-neutral content converter (`cast.content`)

Date: 2026-09-16   Status: Proposed (design record; no implementation yet)

## Problem

The editor API's body converter is the only code that turns the curated author-facing block format into `Post.body`
StreamField values and back, and it is welded to Django REST framework. `src/cast/api/editor/body.py` (445 lines)
imports `EditorValidationError` from `src/cast/api/editor/errors.py:11-18`, an `APIException` subclass, and raises it
from `author_blocks_to_section` (`body.py:229,367`); `src/cast/api/editor/richtext.py:32,87,94` raises the same DRF
exception from inside the sanitizer. No non-DRF caller can use the converter or the sanitizer today, which blocks the
read-only rich-text history audit (`backlog/2026-09-07-editor-richtext-sanitization.md`, Follow-up), the Wagtail v3
adapter evaluation (`backlog/2026-09-08-wagtail-v3-editor-api.md`, "Body format" row), Markdown input and importers.

The converter also duplicates the block schema it converts. `body.py:15` keeps `SUPPORTED_BODY_BLOCKS` (six names)
next to `src/cast/post_body_blocks.py:23-31` `DEFAULT_CONTENT_BLOCK_NAMES` (seven names, `embed` included) and
`default_content_blocks()` (`post_body_blocks.py:58-68`). Built-in blocks go through a 75-line `if`/`elif` chain
(`body.py:289-364`) that re-implements validation the blocks own, while configured custom blocks already take a
generic `to_python` -> `sanitize_block_value` -> `clean` -> `get_prep_value` path (`body.py:272-276`) and a generic
read path (`_custom_author_value`, `body.py:195-200`). The read direction (`section_to_author_blocks`,
`body.py:392-440`) repeats the per-type branching, so an `embed` converter means editing three places plus a frozenset.

Error handling is half-aggregated. Sibling blocks accumulate errors in a plain dict (`body.py:223,237,366`) and
Django `ValidationError` trees are flattened by `_flatten_django_validation_error` (`body.py:156-184`), but the
sanitizer's recursion into `StructBlock`/`ListBlock`/`StreamBlock` values (`richtext.py:91-108`) raises on the first
nested failure, so a custom container with two bad rich-text leaves reports one path per round trip
(BACKLOG.md:112-115).

## Current call sites

| Site | File:line | Owns today |
| --- | --- | --- |
| `author_blocks_to_section` | `api/editor/body.py:213-368` | dispatch, media checks, placeholders, error dict |
| `section_to_author_blocks` | `api/editor/body.py:392-440` | read-side curation, placeholder emission |
| overview wrappers | `api/editor/body.py:371-375,443-445` | compatibility names used by `views.py` |
| `sanitize_rich_text`, `sanitize_block_value` | `api/editor/richtext.py:56-108` | XSS boundary, raw-HTML rejection |
| `get_choosable_image/audio/video` | `api/editor/body.py:37-78` | existence+permission collapsed to `None` (V5) |
| `_content_section`, `_custom_block_map` | `api/editor/body.py:137-147` | unknown prefix -> no custom blocks |
| `_flatten_django_validation_error` | `api/editor/body.py:156-184` | Wagtail block-error tree flattening |
| `editor_exception_handler` | `api/editor/errors.py:86-122` | `{"code": "validation_error", "errors": {...}}` |

Paths that bypass each site today: the write converter has no in-repo bypass, but any non-DRF caller receives a DRF
exception; the read converter skips media checks when `user=None` (by design, `body.py:413,424`); the write converter
with `user=None` works for paragraph-only bodies (`tests/api/editor_richtext_test.py:61-267` rely on it) but crashes
with `AttributeError` on the first media block, because `get_choosable_object` (`body.py:30`) hands `None` to
`CollectionOwnershipPermissionPolicy`, which reads `user.is_active` first (`permission_policies/collections.py:299` in
7.0.9 and 8.0); the sanitizer is bypassed by admin writes, historical revisions and non-API imports; the choose
helpers are reused by `views.py:234,635`; only custom blocks reach the Django flattening; the handler is unchanged.

Tests import private helpers from the API modules: `tests/api/editor_body_test.py:10-21` (`_content_section`,
`_custom_author_value`, `_custom_block_map`, `_flatten_django_validation_error`, `_media_ref_is_available`,
`_unwrap_list_item_values`, `SUPPORTED_OVERVIEW_BLOCKS`; `:157-159` asserts `_content_section("not-body") is None`
and `_custom_block_map(None) == {}`) and `tests/api/editor_richtext_test.py:17-19,196` (`sanitize_*`,
`ContentstateConverter` as a `mocker.patch` target). Acceptance criterion: all 301 tests in
`tests/api/editor_*_test.py` pass unchanged through slices 1-6 (`grep -c "def test_"`: body 81, custom_blocks 5,
episodes 51, media 31, posts 57, publish_preview 26, richtext 21, scopes 29).

## Target design

New package `src/cast/content/` with no `rest_framework` import (enforced by an AST guard test):

```
cast/content/errors.py      ContentError, ErrorCollector, ContentValidationError, flatten_django_validation_error
cast/content/richtext.py    map_rich_text_leaves, normalize_rich_text, sanitize_rich_text, sanitize_block_value
cast/content/media_refs.py  get_choosable_object/image/audio/video (moved from body.py:22-78)
cast/content/blocks.py      BlockConverter, ConversionContext, content_converters(section), built-in converters
cast/content/placeholders.py placeholder_for(index, block, prefix), resolve_placeholder(value, ctx, path, errors)
cast/content/convert.py     author_blocks_to_section, section_to_author_blocks (raising wrappers + collector cores)
```

Contracts (signatures are the design; names are final unless the review log says otherwise):

```python
@dataclass(frozen=True)
class ContentError: path: str; code: str; message: str                      # errors.py
class ErrorCollector:
    def add(self, path: str, code: str, message: str) -> None
    def extend(self, errors: Iterable[ContentError]) -> None
    def __bool__(self) -> bool
    def __len__(self) -> int   # lets a converter detect "errors recorded during my call" (slice 6)
    error_map: dict[str, list[dict[str, str]]]   # property; exact shape of today's EditorValidationError.error_map
class ContentValidationError(Exception):  # __init__(errors: ErrorCollector); .error_map as above
def flatten_django_validation_error(exc: DjangoValidationError, path: str) -> list[ContentError]
@dataclass(frozen=True)
class ConversionContext:       # blocks.py
    section: str | None        # "overview" | "detail"; None => built-ins only (today's _custom_block_map(None))
    user: Any | None           # write: media-ref converters raise TypeError if None; read: None skips the filter
    existing_section: list[dict] | None = None
    path_prefix: str | None = None   # defaults to section; the shim derives section from it as _content_section does
class BlockConverter(Protocol):
    name: str
    editable: bool             # False => always emitted as an unsupported placeholder (embed today)
    def to_stream(self, value: Any, *, ctx: ConversionContext, path: str, errors: ErrorCollector) -> Any | None
    def to_author(self, value: Any, *, ctx: ConversionContext) -> Any | Unsupported
def content_converters(section: str | None) -> dict[str, BlockConverter]
    # built-ins keyed by DEFAULT_CONTENT_BLOCK_NAMES via a module-level table, custom blocks wrapped in
    # GenericBlockConverter(block), None => built-ins only. A test asserts every name has an entry;
    # SUPPORTED_BODY_BLOCKS becomes {c.name for c in built-ins if c.editable}.

def normalize_rich_text(block: RichTextBlock, source: str) -> NormalizedRichText   # richtext.py
    # (source, normalized: str | None, classification: "identical"|"normalized"|"rejected", errors); never raises
def map_rich_text_leaves(block: Block, value: Any, *, path: str, fn: LeafFn) -> Any
    # one recursion over Struct/List/StreamBlock (today's richtext.py:99-107) shared by sanitize and audit
def sanitize_rich_text(block, value: RichText, *, path, errors) -> RichText | None
def sanitize_block_value(block, value, *, path, errors) -> Any   # None leaves mark rejected rich text (slice 6)
def author_blocks_to_section(blocks, *, ctx) -> list[dict]        # convert.py; raises ContentValidationError
def convert_author_blocks(blocks, *, ctx, errors) -> list[dict]  # collector core; never raises for author input
def section_to_author_blocks(section_value, *, ctx) -> list[dict]
```

Data flow on write: `api/editor/views.py` -> `api/editor/body.py` shim -> `content.convert.author_blocks_to_section`
-> per block `content_converters(ctx.section)[type].to_stream(...)`; converters record into the shared collector;
a block that recorded any error contributes nothing to the result (invariant: `errors` non-empty implies raise, so an
unsanitized or unchecked value can never reach `Post.body`). `GenericBlockConverter.to_stream` takes
`before = len(errors)` and returns `None` right after `sanitize_block_value` when `len(errors) > before`, so `clean()`
and `get_prep_value()` never see a rejected (`None`) leaf; otherwise `RichTextBlock.value_for_form` (`value.source`,
`blocks/field_block.py:812` in 8.0) raises `AttributeError` and the broad catch at `body.py:272-285` would add a
spurious `{base}.value: invalid` entry. The shim catches `ContentValidationError` and raises
`EditorValidationError(exc.error_map)`, so `editor_exception_handler` and the envelope are untouched. Read:
`section_to_author_blocks` asks each converter `to_author`; `Unsupported` (a sentinel) becomes the documented
placeholder via `placeholders.placeholder_for`. Placeholder resolution (`body.py:81-134`) moves to
`placeholders.resolve_placeholder`, the single helper the inline-media item extends with an anti-forgery token.

Built-in converters keep the curated format byte-for-byte: `ParagraphConverter`, `CodeConverter`
(`{language, source}`), `ImageConverter`/`AudioConverter`/`VideoConverter` (`{"id": n}`, collapsed `not_found` text
as at `body.py:326,355,362`), `GalleryConverter` (`{"layout": "default", "gallery": [...]}`, `body.py:347-350`),
`EmbedConverter` (`editable=False`), `GenericBlockConverter` (today's custom path incl. `_unwrap_list_item_values`).

Consumers: the audit command iterates `Revision.content["body"]` sections, parsing the value with `json.loads` when it
is a `str` (`migrations/0080_convert_heading_to_paragraph.py:112`; `tests/test_heading_migration.py:117` pins that
fresh revisions store a string), so `cast.content` sees plain block dicts for old and new revisions alike; it calls
`content_converters(section)` and `map_rich_text_leaves(block, block.to_python(value), path=..., fn=record)` where
`record` calls `normalize_rich_text`; no request, no user, no writes. A v3 adapter builds a `ConversionContext` with
`request.user` and maps `ContentValidationError.error_map` onto v3's shape; Markdown input produces author blocks for
the same function, so the author block list is the stable IR.

## Compatibility

Wagtail: every API the converter relies on exists unchanged in 7.0.9
(`.tox/py312-django52-wagtail70/.../wagtail`), 7.4.3 (`.venv`, which currently holds 7.4.3, not 8.0) and 8.0.0
(`.tox/py312-django61-wagtail80`): `ContentstateConverter(features).from_database_format/to_database_format`
(`admin/rich_text/converters/contentstate.py:94-148` in 7.0.9, 92-146 in 8.0), `StreamBlockValidationError`,
`StructBlockValidationError` and `ListBlockValidationError` with `block_errors` dicts and `non_block_errors`
`ErrorList` (7.0.9: `blocks/stream_block.py:36`, `struct_block.py:31`, `list_block.py:25`; 8.0: `stream_block.py:35`,
`struct_block.py:36`, `list_block.py:25`), `RichTextBlock.features` and `.editor` attributes
(`blocks/field_block.py:693-694` in 7.0.9, 763-764 and 773-774 in 8.0), `Block.get_api_representation`,
`Block.clean/to_python/get_prep_value` (`blocks/base.py`), and `features.get_default_features`
(`rich_text/feature_registry.py:48`). No new Wagtail hook is required.

Must stay byte-identical: every error `code`/`message` string in `body.py` and `richtext.py`; the
`{"code": "validation_error", "errors": {...}}` envelope; the placeholder shape
`{"type": "unsupported", "value": {"stored_type", "position"}}` (docs/reference/api.rst:584-597); the documented
author formats (api.rst:542-556); the log line `"Rejected editor API rich text at %s"` (asserted by
`tests/api/editor_richtext_test.py:228` via `caplog.text`; the logger name changes to `cast.content.richtext`, which
no test asserts but which the slice-2a release note must mention for operators filtering by logger). Collector
semantics must match today's dict: per-path `setdefault().extend()`; no reachable input reports one path twice, so
output is identical. Shims: `cast.api.editor.body` and `cast.api.editor.richtext` keep re-exporting every public name
used by `views.py:20-25` plus, until slice 7, the seven private names listed under Current call sites and the
`ContentstateConverter` symbol that `editor_richtext_test.py:196` patches by dotted path. Sibling repos:
`../homepage` (`CAST_POST_BODY_BLOCKS`, `homepage/core/weeknotes/blocks.py:40` nests a `RichTextBlock(features=...)`)
and `../python-podcast` (`pp/show_notes/blocks.py:64,93,108`) configure only custom blocks that already use the
generic path; feature lists resolve through `_rich_text_features` unchanged. No settings, model, URL or template
contract changes, so `../cast-bootstrap5` and `../cast-vue` need no edits; `../daybook/src/daybook/cast_client.py`
speaks only HTTP and compares `type`/`value` (`:950-965`), unaffected.

## Security considerations

- The sanitizer is the write-time XSS boundary from 0.2.65. Moving it must keep: one `ContentstateConverter` per
  operation (`richtext.py:60-62` comment), `ImproperlyConfigured` for configuration failures so custom-block error
  envelopes cannot downgrade them to a 400 (`richtext.py:63-66`), the image/embed feature exclusion, inline `<embed>`
  rejection with code `inline_embed`, and `RawHTMLBlock` rejection at any traversed depth.
- Collector invariant: a converter that records an error returns `None` and the caller never appends; tests assert
  `convert_author_blocks` output is empty for every errored block and `author_blocks_to_section` raises whenever the
  collector is non-empty. Slice 6 keeps partially sanitized containers out via the `len(errors)` skip-clean rule.
- Media references keep existence and permission collapsed into `not_found` (`body.py:23-27`); the write path still
  requires `ctx.user`. Today `user=None` plus a media block is an `AttributeError` inside Wagtail's policy (a 500;
  unreachable over HTTP since DRF supplies `AnonymousUser`, reachable for a v3 adapter or importer that forgets the
  user). `media_refs.get_choosable_object` therefore raises `TypeError("user is required to resolve media refs")`
  when `user is None`: a missing user is a programming error, never a silent skip or a `not_found` that looks like
  author input. Paragraph-only writes with `user=None` keep working (the richtext tests depend on it); the read
  path's `user=None` skip stays explicit in the `ConversionContext` docstring.
- `normalize_rich_text` is read-only and never persists; the audit tool must not be handed a code path that writes.
- Placeholder resolution keeps `position` + `stored_type` matching against `existing_section`; centralizing it does
  not weaken it, and the inline-media follow-up adds its anti-forgery token there, nowhere else.

## Implementation slices

Sizes are **changed lines** (additions plus deletions), so moved code counts twice; "move-heavy" slices are mostly
relocation guarded by the existing tests. Ten slices, not eight, because of that double counting.

1. **Error collector** — add `cast/content/__init__.py`, `content/errors.py` (`ContentError`, `ErrorCollector`,
   `ContentValidationError`, `flatten_django_validation_error` moved from `body.py:150-192`); `body.py` builds its
   errors through the collector and raises `EditorValidationError(collector.error_map)`;
   `_flatten_django_validation_error` stays as an alias returning the old dict shape. Tests: `tests/content/
   errors_test.py` (add/extend/bool/len/error_map; flattening cases at `editor_body_test.py:161-199` stay until
   slice 7). Docs: none. ~240 changed lines.
2a. **Rich text move** — `content/richtext.py` holds today's `richtext.py` verbatim except that the sanitize
   functions take `errors: ErrorCollector`; `api/editor/richtext.py` becomes a shim that re-exports
   `ContentstateConverter` and wraps the two sanitize functions to raise `EditorValidationError`. Add the AST guard
   test (`tests/content/no_drf_import_test.py`, after `tests/import_cycle_test.py`). Existing tests unchanged. Docs:
   `docs/releases/0.2.65.rst` bullet for the logger rename (`cast.api.editor.richtext` -> `cast.content.richtext`),
   in this commit per AGENTS.md:43,46. ~280 changed lines, move-heavy.
2b. **Walker and normalizer** — `map_rich_text_leaves` (the sanitizer recursion rewritten as a callback walk) and
   `normalize_rich_text`; `sanitize_block_value` becomes `map_rich_text_leaves(..., fn=sanitize)`. Tests: the three
   classifications on raw revision-style input without a user; the walker on Struct/List/Stream values and
   `RawHTMLBlock` at depth. Docs: none. ~150 changed lines. Prerequisite for the rich-text history audit.
3. **Registry skeleton** — `content/media_refs.py` (move `body.py:22-78`; import `audio_permission_policy` from
   `media_permissions.py`, add `video_permission_policy` there and the `user is None` `TypeError`);
   `content/blocks.py` with `ConversionContext`, `BlockConverter`, `content_converters(section)`,
   `GenericBlockConverter`, `ParagraphConverter`, `EmbedConverter`; `body.py` dispatches through the registry, falling
   back to the remaining chain for code/image/gallery/audio/video; `_content_section`/`_custom_block_map` stay as thin
   wrappers over `content_converters` so `editor_body_test.py:157-159` keeps passing. Tests:
   `content_converters(None)` returns built-ins only and every name it answers resolves to a converter;
   `get_choosable_image(1, None)` raises `TypeError`. The "every `DEFAULT_CONTENT_BLOCK_NAME` has a converter"
   assertion belongs to 4b, where the last built-in converter lands; until then the registry is deliberately
   partial and `body.py` still falls back to the chain.
   Partial V5: switches `body.py`'s two policy sites (`:53,72`); `forms.py:98`, `wagtail_hooks.py:61,81`,
   `api/editor/media.py:35-36`, `views/video.py:16`, `views/voxhelm.py:24` and the AST guard stay with V5. Docs: none.
   ~270 changed lines, move-heavy.
4a. **Code and media-ref converters** — `CodeConverter` plus a `MediaRefConverter` base for
   `ImageConverter`/`AudioConverter`/`VideoConverter` with `to_stream` and `to_author`; delete their write and read
   branches from the chain. Tests: per-converter unit tests in `tests/content/blocks_test.py` (`not_found` message
   text, read-side `user=None` skip). ~240 changed lines.
4b. **Gallery converter and chain removal** — `GalleryConverter`; delete what is left of `body.py:289-364` and
   `401-430`; derive `SUPPORTED_BODY_BLOCKS` from the registry. Tests: gallery unit tests; the derivation test; the
   registry completeness test (every `DEFAULT_CONTENT_BLOCK_NAME` has a converter), which first passes here.
   ~160 changed lines. Prerequisite for the embed block item (`EmbedConverter.to_stream` replaces `editable=False`).
5a. **Placeholders** — `content/placeholders.py` takes over `body.py:81-134` (`placeholder_for`,
   `resolve_placeholder` writing into the collector); `body.py` calls it. Existing placeholder tests cover it. Docs:
   none. ~120 changed lines, move-heavy.
5b. **Convert + shim** — `content/convert.py` takes over `author_blocks_to_section`/`convert_author_blocks`/
   `section_to_author_blocks`; `api/editor/body.py` shrinks to the DRF shim (public re-exports for `views.py`, the
   private re-exports listed in Compatibility, `ContentValidationError` -> `EditorValidationError`, path-prefix ->
   section derivation as `_content_section` does today). Tests: collector-invariant test (`convert_author_blocks`
   output empty for every errored block). `docs/architecture.rst` module tree gains `content/` with a two-line
   description. ~240 changed lines. Prerequisite for the v3 adapter, Markdown input and inline-media placeholders.
6. **Nested error aggregation** (behavior change) — `sanitize_block_value` records and continues, leaving `None` at
   rejected leaves; `GenericBlockConverter.to_stream` returns `None` when `len(errors)` grew during sanitize. Tests:
   two bad rich-text leaves in one `ListBlock(StructBlock)` via the HTTP API and via `convert_author_blocks`, asserting
   the error map holds exactly the two leaf paths and no `{base}.value` entry; the one-bad-leaf map pinned at
   `tests/api/editor_custom_blocks_test.py:120-140` stays unchanged. Docs: api.rst:558-570 custom-block paragraph,
   a `docs/releases/0.2.65.rst` bullet for aggregated nested errors; close BACKLOG.md:112-115. ~130 changed lines.
7. **Test relocation and shim trim** — move private-helper tests (`editor_body_test.py:157-215,282,545-547`) to
   `tests/content/`, import from `cast.content`, drop the private re-exports from the shim; keep public re-exports.
   ~200 changed lines, mostly moved. Not a prerequisite for anything; it makes the "unchanged tests" shim temporary.

Each slice runs `just check` (100% coverage, mypy strict defs) and gets its own commit; the full tox matrix runs after
slice 2b and slice 5b because both touch code that the Wagtail 7.0 and 8.0 environments exercise differently.

## Risks and open questions

1. **Where the registry lives.** The review (D11) suggests `post_body_blocks`; this note puts it in
   `cast.content.blocks` because media converters need `cast.models.Audio/Video` policies and `models/pages.py`
   imports `post_body_blocks` (`ContentBlock.deconstruct`), so a registry there recreates the cycle `body.py` dodges
   with local imports. Recommendation: `cast.content.blocks` owns converters, `post_body_blocks` owns the schema.
2. **`user=None` on write with media blocks.** Today: `AttributeError` from Wagtail's policy. Options: (a) explicit
   `TypeError` in `get_choosable_object` (one place; also covers `views.py:234,635`); (b) treat `None` as
   `AnonymousUser`, yielding `not_found` for every ref. (b) reads as "author referenced a missing image" when the fault
   is the caller's, and makes write-`None` mean "deny" while read-`None` means "skip". Recommendation: (a); revisit
   only if the v3 adapter shows a caller that legitimately has no user.
3. **Classification granularity for the audit.** `normalize_rich_text` returns identical/normalized/rejected; the
   audit item also wants "unsafe construct removed". Options: (a) a marker scan (script/style tags, `on*` attributes,
   unsafe schemes) as `RichTextScan` in `content.richtext`; (b) leave it to the audit command. Recommendation: (b)
   here, (a) as the first slice of the audit item, reusing `_RichTextInput`.
4. **Public API status of `cast.content`.** Documenting it in `docs/reference/` would make it a supported extension
   point (deprecation duty). Recommendation: architecture.rst only until the v3 evaluation decides.
5. **Slice 6 changes client-visible error counts**; daybook only reads `code` values (`cast_client.py:714-716`), so
   more paths are safe, but the release note must say so.

## Non-goals

No new block types (embed stays a placeholder), no change to documented request/response shapes or error codes, no
change to `editor_exception_handler`, no publication-policy or media-ingestion work, no read-model changes, no
Markdown parser, no audit command (only the callable it needs), no permission-policy semantics changes beyond moving
the video policy into `media_permissions.py`, no completion of V5 (seven policy sites and its AST guard stay open).

## Done when

- `cast.content` exists with the modules above, imports no `rest_framework`, and an AST guard test proves it.
- `api/editor/body.py` and `api/editor/richtext.py` are shims under 80 lines each with no block-type branching.
- All 301 `tests/api/editor_*_test.py` tests pass unchanged through slice 6; slice 7 relocates them unchanged.
- A test asserts every `DEFAULT_CONTENT_BLOCK_NAME` has a converter and `SUPPORTED_BODY_BLOCKS` is derived from it.
- `normalize_rich_text(block, source)` runs on raw revision content without a request or user (test included).
- `get_choosable_*` with `user=None` raises `TypeError` (test included); paragraph-only writes with `user=None` pass.
- Nested sanitizer errors aggregate with no spurious container-level entry; api.rst, release notes and BACKLOG.md
  reflect it; the logger rename is in the release notes from slice 2a onward.
- `just check` green per slice; full tox matrix green after slices 2b and 5b.

## Review log

- warning, accepted: `user=None` write claim was wrong (`collections.py:299` reads `user.is_active` in 7.0.9 and 8.0);
  Security states today's `AttributeError`, adopts `TypeError` in `get_choosable_object` with tests; Risks #2 redone.
- warning, accepted: `_content_section`/`_custom_block_map` (`editor_body_test.py:12,14,157-159`) added to the table
  and private re-export list; slice 3 keeps both as wrappers over `content_converters`.
- warning, accepted: verified `RichTextBlock.value_for_form` returns `value.source`; added `ErrorCollector.__len__`,
  the skip-clean rule in `GenericBlockConverter.to_stream`, and the "exactly two leaf paths" assertion in slice 6.
- warning, accepted: logger-rename release-note bullet moved into slice 2a (AGENTS.md:43,46); slice 6 keeps its own.
- warning, accepted: sizes restated as changed lines; slices 2, 4 and 5 split into a/b; tox checkpoints now 2b and 5b.
- suggestion, accepted: Wagtail error-class anchors labelled per version (7.0.9: 36/31/25; 8.0: 35/36/25).
- suggestion, accepted: slice 3 is "partial V5" naming the seven remaining sites and the AST guard; Non-goals agrees.
- suggestion, accepted: `section: str | None`; `content_converters(None)` = built-ins; shim derives it as today.
- suggestion, accepted: consumer sketch parses `content["body"]` with `json.loads` when it is a `str`
  (`0080_convert_heading_to_paragraph.py:112`, `tests/test_heading_migration.py:117`).
- warning, accepted (round 1): the "every `DEFAULT_CONTENT_BLOCK_NAME` has a converter" assertion cannot pass at
  slice 3, which only adds paragraph, embed and the generic converter. Moved to 4b; slice 3 asserts the weaker
  invariant that every name the registry answers resolves to a converter.
