# Programmatic Content Editing API

Date: 2026-06-19

Status: Draft PRD; implementation not started.

## Summary

django-cast should provide a trusted, authenticated content editing API that lets external tools and agents create,
update, preview, publish, and revise posts or episodes without direct database access or production shell access.

The first target workflow is assisted authoring: a local or hosted agent receives a directory of recent notes,
reviews existing archive content through the public/read API, drafts a new post from those inputs, attaches existing
or newly uploaded media, and returns a Wagtail draft preview URL for human review. The API must be generic across
django-cast sites and blogs. Clients select an editable parent `Blog` or `Podcast` page by identifier, and permissions
are checked against that target page and the requesting user or token.

## Motivation

Current automation options are too coarse or too risky:

- A management command requires shell access to the server that owns production content.
- Local database editing followed by a database push risks overwriting unrelated production changes.
- Existing read APIs expose enough content to inspect archives, but there is no matching write surface for safe draft
  creation, review, and publication.
- Wagtail admin remains the right human editing interface, but agents need a smaller, stable contract that maps common
  authoring concepts onto django-cast's StreamField and revision behavior.

The API should make the safe path the easy path: create a draft revision, preview it, let a human revise or publish it,
and preserve Wagtail's page permissions and revision history.

## Observed Authoring Requirements

A representative weeknotes corpus from an existing django-cast-backed site shows that a useful first slice needs more
than plain text:

- Rich text paragraphs with headings, lists, blockquotes, horizontal rules, links, and inline code.
- Code blocks with explicit language and source text.
- Existing image references for cover images, single image blocks, and gallery blocks.
- Tags for grouping recurring series such as weeknotes.
- Stable preview/edit links so a human can inspect the generated draft in Wagtail.

The same API must also leave room for podcast episodes, audio attachments, video attachments, embeds, categories, and
future import/upload workflows, even if those are not all implemented in the first slice.

## Goals

- Provide a DRF-backed write API for trusted clients to create draft posts under any editable django-cast `Blog`.
- Design the endpoint shape so the same permission, revision, body, and media rules can later support `Episode`
  pages under any editable django-cast `Podcast`.
- Accept author-friendly body input instead of requiring clients to construct raw Wagtail StreamField internals.
- Preserve Wagtail draft/live semantics by creating revisions first and publishing only through an explicit publish
  action.
- Return structured validation errors that agents can use to repair failed requests.
- Support conflict detection for updates so agents cannot silently overwrite newer human edits.
- Keep the API independent of any one consumer site, theme, or blog instance.
- Authenticate with django-indieweb's IndieAuth scoped tokens rather than coarse, non-expiring credentials.

## Non-Goals

- Replacing the Wagtail admin editing experience.
- Adding local-to-production database synchronization.
- Requiring agents to log in over SSH or run management commands on production hosts.
- Designing a site-specific weeknotes generator inside django-cast.
- Supporting arbitrary raw database writes or raw StreamField JSON as the primary client contract.
- Publishing generated content without an explicit authenticated publish action.

## Actors

- Human editor: authorizes a client through the IndieAuth flow (granting scopes), chooses the target blog or podcast,
  reviews previews, and may publish the draft.
- Trusted client or agent: reads source notes and archive content, submits drafts and updates, handles validation
  errors, and presents preview links.
- django-cast API: validates permissions, converts authoring payloads to model fields and StreamField blocks, stores
  revisions, and exposes preview/edit/publish affordances.

## Proposed API Shape

The exact URL prefix can follow existing project conventions, but the write API should live alongside the existing
cast API rather than in a consumer site:

- `GET /api/editor/parents/`
  - List `Blog` and `Podcast` pages the caller may add content to.
- `POST /api/editor/posts/`
  - Create a draft post under a selected `Blog`.
- `GET /api/editor/posts/{id}/`
  - Return editable metadata, body source, current revision metadata, and admin URLs for one post.
- `PATCH /api/editor/posts/{id}/`
  - Update a draft by creating a new revision. Requires conflict metadata.
- `POST /api/editor/posts/{id}/preview/`
  - Return preview URL or rendered preview metadata for the current draft revision.
- `POST /api/editor/posts/{id}/publish/`
  - Publish an existing revision. This can be deferred until after the draft-create slice.

Future episode endpoints should mirror the same shape:

- `POST /api/editor/episodes/`
- `GET /api/editor/episodes/{id}/`
- `PATCH /api/editor/episodes/{id}/`
- `POST /api/editor/episodes/{id}/preview/`
- `POST /api/editor/episodes/{id}/publish/`

### Why the editor API has its own read endpoints

The existing read API is not a substitute for the editor `GET` endpoints, because it serves a different audience:

- The Wagtail pages API (`GET /api/wagtail/pages/{id}/`) is `AllowAny` and, by Wagtail default, returns only live
  pages. The editor workflow produces **drafts**, which never appear there; a client cannot read back the draft it just
  created.
- It exposes raw StreamField plus rendered `html_overview`/`html_detail`, not the normalized authoring source the write
  API round-trips. Safe patching of an existing draft needs that authoring representation, not rendered HTML.
- It does not expose revision metadata such as `latest_revision_id`, which conflict detection (`base_revision_id` /
  `If-Match`) depends on.
- No existing endpoint lists `Blog`/`Podcast` pages filtered by the caller's add-child permission;
  `GET /api/editor/parents/` fills that gap.

The editor `GET` endpoints are therefore permission-scoped views over draft-aware, revision-aware, authoring-shaped data.
If the first slice ships create-only, `GET /api/editor/posts/{id}/` can be deferred until update/round-trip support needs
it, since the create response already returns the preview, edit, and API URLs plus the latest revision ID.

## Create Post Request

The first implementation should prefer Markdown plus structured metadata:

```json
{
  "parent": {
    "id": 123
  },
  "title": "Weeknotes 2026-25",
  "slug": "weeknotes-2026-25",
  "visible_date": "2026-06-19T18:00:00+02:00",
  "cover_image": {
    "id": 456,
    "alt_text": "Notebook and laptop on a desk"
  },
  "tags": ["weeknotes"],
  "categories": [],
  "overview_markdown": "## Notes\n\n- Shipped the first draft.\n\n```python\nprint(\"hello\")\n```",
  "media": [
    {
      "kind": "gallery",
      "placement": "append",
      "images": [{"id": 456}, {"id": 789}]
    }
  ],
  "publish": false
}
```

Response:

```json
{
  "id": 987,
  "type": "cast.Post",
  "title": "Weeknotes 2026-25",
  "slug": "weeknotes-2026-25",
  "parent": {"id": 123},
  "latest_revision_id": 6543,
  "live": false,
  "status": "draft",
  "preview_url": "/admin/pages/987/view_draft/",
  "edit_url": "/admin/pages/987/edit/",
  "api_url": "/api/editor/posts/987/"
}
```

## Body Serialization

Clients should not need to know Wagtail's full StreamField storage format. The API should expose two body input tiers.

Tier 1, first slice:

- `overview_markdown` converts Markdown into the `overview` section of `Post.body`.
- Paragraph/rich text output must preserve headings, lists, blockquotes, horizontal rules, links, and inline code.
- Fenced code blocks convert to django-cast code blocks with `{ "language": "...", "source": "..." }`.
- Image and gallery placement can be supplied through structured `media` instructions that reference existing image IDs.

Tier 2, later:

- `body_blocks` accepts a normalized django-cast authoring format with block types such as `paragraph`, `heading`,
  `code`, `image`, `gallery`, `embed`, `video`, `audio`, `overview`, and `detail`.
- The server still owns conversion to Wagtail StreamField values and block IDs.
- A read endpoint can return both rendered values and normalized source so agents can patch existing drafts safely.

The initial post implementation can write only the `overview` section. It should not block a later extension that lets
clients explicitly address `overview` and `detail`.

## Media Handling

First slice:

- Cover images, image blocks, and gallery blocks may reference existing Wagtail image IDs.
- The API validates that referenced images exist and are visible to the caller.
- The response includes structured errors for missing images or invalid placements.

Later slices:

- Upload new images through a dedicated endpoint or an existing Wagtail image API wrapper.
- Import images from remote URLs after explicit server-side validation.
- Support audio and video attachment workflows for episodes and media-rich posts.
- Return generated rendition metadata when useful for preview clients.

## Tags And Categories

The write API should support tag assignment from the first slice because recurring series and archive workflows depend
on it. Tags should be supplied as names, matching the Wagtail admin tag widget, and the server should normalize them
using the same model behavior as Wagtail admin saves.

Categories can be optional in the first slice, but the API shape should include them so sites that use categories do
not need a different endpoint contract later. Unlike tags, categories should reference existing `PostCategory` records
by stable identifier, such as ID or slug, and should not be created implicitly from the payload.

Read APIs should eventually expose per-page tags and categories for editable content. The existing faceted read API is
useful for discovery, but aggregate facets are not enough for safe round-tripping of one post.

## Authentication And Permissions

Authentication reuses django-indieweb's IndieAuth instead of DRF's default token. A client obtains a token through the
IndieAuth authorization-code flow: the user authenticates with their normal Django login in a browser, consents to a set
of scopes, and the tool receives a **scoped, expiring, revocable** token (with PKCE and a client allowlist). This matches
the "open a browser window to authenticate" model directly and avoids DRF `TokenAuthentication`'s single, unscoped,
non-expiring bearer credential. Scopes map to actions (for example create/update/publish), so a drafting agent need not
hold publish rights. Session authentication may additionally be accepted for same-origin browser tools, but it is not the
primary mechanism for headless agents. See Alternatives Considered for why the default DRF token was rejected as the
foundation.

Every write must check Wagtail permissions for the selected parent or page:

- Creating a post requires permission to add a child page under the selected `Blog`.
- Updating a post requires edit permission for that page.
- Previewing a draft requires permission to view or edit the draft.
- Publishing requires publish permission for that page and must be a separate action.

The API must not rely on `is_staff` alone, and it must not assume a single blog per site.

## Drafts, Revisions, And Publishing

Creates and updates should save draft revisions by default. A request field such as `"publish": false` may be accepted
for explicitness, but publishing should not be the default behavior.

When publish support is implemented, it should publish a selected revision through Wagtail's revision publishing path
instead of mutating live page fields directly. That keeps Wagtail history intact and lets django-cast hooks such as
podcast episode numbering run consistently for programmatic publishes and admin publishes.

Publish response metadata should include the published revision ID, live URL, and any model-specific side effects that
the client may need to display.

## Conflict Detection

Update requests must include either `base_revision_id` in the JSON body or an equivalent `If-Match`/ETag header. If the
current latest revision differs from the client's base revision, the API returns `409 Conflict` with enough metadata for
the client to reload and ask for human review.

Example update:

```json
{
  "base_revision_id": 6543,
  "title": "Weeknotes 2026-25",
  "overview_markdown": "Updated draft text."
}
```

Conflict response:

```json
{
  "code": "revision_conflict",
  "detail": "The page has a newer revision than the submitted base revision.",
  "current_revision_id": 6550,
  "submitted_base_revision_id": 6543,
  "edit_url": "/admin/pages/987/edit/"
}
```

## Validation Errors

Validation errors should be stable and machine-readable:

```json
{
  "code": "validation_error",
  "errors": {
    "title": [{"code": "required", "message": "This field is required."}],
    "parent": [{"code": "permission_denied", "message": "You cannot add posts under this page."}],
    "media.0.images.1.id": [{"code": "not_found", "message": "Image 789 does not exist."}]
  }
}
```

The API should prefer precise field paths over broad failure messages so an agent can repair a request without guessing.

## First Implementation Slice

Implement the smallest useful workflow for assisted post authoring:

1. Add IndieAuth-authenticated `POST /api/editor/posts/` draft creation for `Post` pages under caller-selected `Blog`
   parents.
2. Accept title, slug, visible date, tags, optional categories, optional cover image ID, `overview_markdown`, and optional
   image/gallery references to existing images.
3. Convert Markdown to the `overview` StreamField section, including rich text paragraphs and fenced code blocks.
4. Save a Wagtail draft revision and return page ID, latest revision ID, preview URL, edit URL, and API URL.
5. Add read support for editable post metadata needed by clients to show or revise the generated draft.
6. Document that publish remains a separate follow-up unless it is implemented in the same change.

## Test Scenarios

- Authenticated editor can create a draft post under an editable blog and receives preview/edit URLs.
- Anonymous users and authenticated users without add permission cannot create posts.
- A token whose scopes omit publish can create and update drafts but cannot publish.
- The same API works with two different blog parents and never assumes a site-specific blog.
- Tags are created or resolved consistently with Wagtail/admin behavior.
- Existing cover image, image block, and gallery image IDs are accepted and missing image IDs return structured errors.
- Markdown headings, lists, blockquotes, horizontal rules, links, inline code, and fenced code blocks round-trip into
  django-cast body blocks.
- Draft creation does not publish the page by default.
- Updating with a stale `base_revision_id` returns `409 Conflict`.
- Publishing, once added, uses Wagtail revision publishing and respects publish permissions.
- Episode endpoints, once added, enforce episode-specific validation such as required podcast audio on publish.

## Alternatives Considered

### django-indieweb Micropub as the full write surface

django-indieweb provides a mature, security-audited Micropub implementation with a pluggable content handler, so a
`WagtailMicropubHandler` could map Micropub `h-entry` properties onto `Post`/`Episode` pages and reuse its
create/update/delete/source machinery. This was rejected as the *agent-authoring* contract for three reasons:

- **Data-model impedance.** Micropub is flat `h-entry` properties; django-cast authoring is structured (StreamField
  overview/detail sections, code blocks with language, galleries, cover image + alt text, tags-by-name vs
  categories-by-id, episode audio). Expressing this requires non-standard `mp-*` extensions, which forfeits the
  standards-interop benefit.
- **Wagtail draft/preview/revision/conflict semantics are not Micropub concepts.** The core workflow — create a draft
  revision, return a Wagtail preview URL, let a human review, then publish, with conflict detection by
  `base_revision_id` — would be bolted onto a publish-oriented protocol.
- **Coarse errors.** The agent-repair contract needs field-precise validation paths (for example
  `media.0.images.1.id`); Micropub errors are request-level (`invalid_request`, `forbidden`).

What *is* reused from django-indieweb is its IndieAuth authentication (see Authentication And Permissions). A thin
Micropub handler may still be added later as an additional surface purely for standard Micropub clients, separate from
the agent-authoring API.

### Driving the Wagtail admin via Playwright

Automating the human Wagtail admin with a headless browser would need no new server code and would stay in feature parity
with Wagtail. It was rejected as a foundation because it is brittle against admin template/JS and Wagtail-upgrade
changes, the StreamField block UI is hard to automate reliably, it offers no machine-readable validation errors (agent
self-repair would mean scraping the DOM), it is slow (a full browser per operation), and it requires a logged-in headless
browser pointed at the production admin — an operational risk comparable to the shell/database access this API exists to
avoid. It remains acceptable only as a throwaway MVP to validate the workflow, not as a stable agent contract. This does
not conflict with the "do not replace the admin" non-goal: Playwright would *use* the human UI, and it is rejected on
robustness, not philosophy.

### DRF default token authentication

DRF `TokenAuthentication` is convenient, but its default token is unscoped (full account access), non-expiring, and
revocable only by hand. It is acceptable only for a trusted single-user local slice over HTTPS, and was rejected as the
security foundation in favor of IndieAuth scoped tokens.

## Open Questions

- Authentication is decided: IndieAuth scoped tokens (see Authentication And Permissions). Residual question: should the
  first slice also accept session authentication for same-origin browser tools, or IndieAuth tokens only?
- What scope granularity should IndieAuth expose for this API (for example a single content scope versus separate
  create/update/publish scopes)?
- Should Markdown conversion live in django-cast directly, or behind a small optional dependency?
- Should normalized `body_blocks` be implemented alongside Markdown in the first slice, or deferred until update support
  needs more precise patching?
- What is the right endpoint namespace: `editor`, `content`, or a Wagtail-compatible extension?
- Should publish-by-request be allowed in the create endpoint for callers with publish permission, or only through a
  separate publish endpoint?
- How should remote image import be constrained so it is useful for agents but safe for production sites?
