# Editor API support for configured custom post body blocks

Status: implemented for 0.2.62. The editor API now accepts configured custom
body blocks for their configured `overview`/`detail` section, validates them
through the Wagtail block API, and serializes them back to author-facing values
instead of `unsupported` placeholders. Custom blocks remain a trusted site-level
extension point; blocks that reference images, pages, snippets, or media are
responsible for their own permission semantics.

## Problem

The editor API currently understands django-cast's built-in post body block
contract, but custom blocks configured through `CAST_POST_BODY_BLOCKS` are not a
first-class round-trip shape for API clients. Homepage's `weeknote_links` block
needs daybook to create/update/read a custom overview block without hand-writing
Wagtail's internal `ListBlock` storage wrappers and without receiving
`unsupported` placeholders on read.

## Goal

Extend the editor API so configured custom post body blocks can round-trip
through author-facing values.

Required behavior:

- Discover configured custom block types from `CAST_POST_BODY_BLOCKS` for both
  `overview` and `detail` body sections.
- Accept an author-facing value shape for a configured custom block type. For
  homepage's weeknote use case this is:

  ```json
  {
    "type": "weeknote_links",
    "value": [
      {
        "category": "articles",
        "kind": "article",
        "title": "Example article",
        "url": "https://example.com/article",
        "source": "Example",
        "source_url": "",
        "description": "<p>Short summary.</p>"
      }
    ]
  }
  ```

- Convert incoming author-facing values through the configured Wagtail block API:
  `to_python()`, `clean()`, then `get_prep_value()`.
- Return validation errors from Wagtail block cleaning in a client-usable shape,
  preserving field-specific errors for nested custom values where possible.
- Serialize configured custom blocks back to the author-facing API shape on read,
  rather than returning `unsupported` placeholders.
- Cover create, update, and read flows for posts and episodes where the relevant
  body section allows custom blocks.

## Acceptance notes

- Daybook can create a post containing `overview` -> `weeknote_links`, update it,
  and read it back with the same author-facing values.
- Invalid custom values fail through Wagtail block validation, not ad-hoc API-only
  checks.
- The API does not expose or require Wagtail's internal `ListBlock` item wrapper
  shape (`type: item`, generated `id`) from clients.
- No django-cast code change is part of the homepage weeknote-links feature; this
  backlog item tracks the follow-up.
