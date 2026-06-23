# Programmatic Content Editing API

Date: 2026-06-19

Status: Slice 1 implemented (2026-06-22): `GET /api/editor/parents/`, `POST /api/editor/posts/`, and
`GET /api/editor/posts/{id}/` are shipped. The API is authentication-mechanism agnostic, authenticates with Django
session auth in the first slice, and authorizes with Wagtail page permissions. The body contract is a structured block
list (heading, paragraph, code, image, gallery, audio).

Slice 2 implemented (2026-06-23): **updating drafts** via `PATCH /api/editor/posts/{id}/` with revision-based conflict
detection (`409`). `PATCH` requires `base_revision_id`, saves a new Wagtail draft revision, leaves omitted fields
untouched, replaces the whole `overview` section when supplied, and supports explicit `cover_image: null` to clear the
draft cover image.

Remaining follow-ups beyond slice 2: publish action, Markdown convenience input, scoped-token (IndieAuth) auth, and
embed/video blocks.

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
- Accept a structured, lossless body block list instead of requiring clients to construct raw Wagtail StreamField
  internals (block IDs, storage format), and without forcing a Markdown parser into the request path.
- Preserve Wagtail draft/live semantics by creating revisions first and publishing only through an explicit publish
  action.
- Return structured validation errors that agents can use to repair failed requests.
- Support conflict detection for updates so agents cannot silently overwrite newer human edits.
- Keep the API independent of any one consumer site, theme, or blog instance.
- Keep django-cast independent of any single authentication mechanism: the API depends only on an authenticated
  `request.user` and Wagtail page permissions, so sites can plug in session auth, DRF tokens, or IndieAuth scoped
  tokens without changing endpoint code.

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

The first implementation accepts a structured `overview` block list plus structured metadata:

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
  "overview": [
    {"type": "heading", "value": "Notes"},
    {"type": "paragraph", "value": "<p>Shipped the first draft.</p>"},
    {"type": "code", "value": {"language": "python", "source": "print(\"hello\")"}},
    {"type": "gallery", "value": [{"id": 456}, {"id": 789}]}
  ],
  "publish": false
}
```

Image and gallery placement is expressed inline as `image`/`gallery` blocks within the `overview` list, so block order
is explicit rather than inferred from a separate `media` instruction stream.

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

`Post.body` is a Wagtail StreamField with `overview` and `detail` sections; each section is an ordered list of typed
blocks (`heading`, `paragraph`, `code`, `image`, `gallery`, `embed`, `video`, `audio` — see
`src/cast/post_body_blocks.py`). The `paragraph` block is a `RichTextBlock` whose value is stored as HTML. The API
contract should map directly onto that block-list shape rather than onto a prose format, for two reasons:

- The primary client is an agent, which natively emits structured JSON. A structured block list is lossless and
  unambiguous; a prose format like Markdown forces the server to *guess* the mapping (is `## X` a `heading` block or
  rich text inside a `paragraph`? how do nested lists/blockquotes flatten into paragraph HTML?).
- Safe `PATCH`/round-trip editing needs the structured representation anyway — rendered HTML cannot be reliably diffed
  and patched. Building the structured contract first avoids a throwaway Markdown-only path.

Tier 1, first slice — structured block list:

- The request supplies the `overview` section as an ordered list of `{ "type": ..., "value": ... }` blocks using
  django-cast's existing block names. Example: `{"type": "heading", "value": "Notes"}`,
  `{"type": "paragraph", "value": "<p>Shipped the first draft.</p>"}`,
  `{"type": "code", "value": {"language": "python", "source": "print('hi')"}}`.
- The server owns conversion to Wagtail StreamField values and block IDs; clients never construct raw StreamField
  internals.
- `paragraph` values are rich-text HTML, validated/sanitized through the same path Wagtail uses on admin save.
- Image and gallery blocks reference existing image IDs (see Media Handling).
- A read endpoint returns the same normalized block list (plus rendered values where useful) so agents can patch
  existing drafts safely.

The initial post implementation writes only the `overview` section. The block-list contract must not block a later
extension that lets clients explicitly address both `overview` and `detail`.

Tier 2, later — optional Markdown convenience:

- An optional `overview_markdown` input may be added later as a convenience for human-driven or Markdown-native
  clients. It would be converted server-side into the same block list, behind an optional dependency so the Markdown
  parser is not forced onto all installs.
- This is explicitly *not* part of the first slice; the structured block list is the canonical contract.

## Media Handling

First slice:

- Cover images, and inline `image`/`gallery` blocks in the `overview` list, may reference existing Wagtail image IDs.
- The API validates that referenced images exist and are visible to the caller.
- The response includes structured errors for missing images or invalid block values, using the block's path in the
  `overview` list (for example `overview.3.value.1.id`).

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

**django-cast stays authentication-mechanism agnostic.** The editor API depends only on two things from a request: an
authenticated `request.user`, and that user passing the Wagtail page-permission check for the requested action. *How*
the user authenticated is a pluggable DRF concern (`authentication_classes` / `DEFAULT_AUTHENTICATION_CLASSES`), not
something the endpoint code hardcodes. This keeps the clean boundary:

- **django-cast owns authorization** — Wagtail page permissions per action. These already exist and are independent of
  any auth mechanism.
- **The site/deployment owns authentication** — it chooses the authentication class(es). django-cast ships sane
  defaults and never imports a specific auth provider.

First slice: authenticate with Django **session authentication** plus Wagtail page permissions. This is the smallest
path to a working create endpoint and requires no new auth subsystem.

Later, a site that wants scoped, expiring, revocable tokens for headless agents can add **django-indieweb's IndieAuth**
(authorization-code flow with PKCE and a client allowlist) purely as an additional authentication class in its settings,
with **no editor-API code changes**. DRF `TokenAuthentication` is another drop-in option for a trusted single-user slice
(see Alternatives Considered for its trade-offs).

**Scopes (the one nuance).** Scoped-token schemes like IndieAuth carry per-action scopes (for example create / update /
publish), so a drafting agent need not hold publish rights. To keep django-cast auth-agnostic, scope enforcement lives
in a small, generic permission class that reads `request.auth` scopes against an action→required-scope mapping — it does
not know or import IndieAuth. Under session auth `request.auth` is `None` and authorization falls back to pure Wagtail
permissions. django-cast therefore exposes the action→scope mapping that any scoped-token backend can satisfy, without
depending on one.

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
  "overview": [
    {"type": "paragraph", "value": "<p>Updated draft text.</p>"}
  ]
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
    "overview.3.value.1.id": [{"code": "not_found", "message": "Image 789 does not exist."}]
  }
}
```

The API should prefer precise field paths over broad failure messages so an agent can repair a request without guessing.

## First Implementation Slice

Implement the smallest useful workflow for assisted post authoring:

1. Add session-authenticated `POST /api/editor/posts/` draft creation for `Post` pages under caller-selected `Blog`
   parents, authorized by Wagtail add-child permission, with the API kept authentication-mechanism agnostic.
2. Accept title, slug, visible date, tags, optional categories, optional cover image ID, a structured `overview` block
   list, and inline `image`/`gallery` blocks referencing existing images.
3. Convert the `overview` block list into the `overview` StreamField section, owning Wagtail StreamField values and
   block IDs server-side (paragraph rich-text HTML validated through Wagtail's normal save path).
4. Save a Wagtail draft revision and return page ID, latest revision ID, preview URL, edit URL, and API URL.
5. Add read support for editable post metadata and the normalized `overview` block list needed by clients to show or
   revise the generated draft.
6. Document that publish remains a separate follow-up unless it is implemented in the same change.

## Second Implementation Slice

Status: Implemented 2026-06-23.

Let a client safely revise a draft it (or a human) created, by saving a new Wagtail revision on top of the latest one,
with conflict detection so it never silently overwrites a newer human edit. This slice deliberately reuses slice 1's
conversion module, structured error envelope, media `choose`-permission checks, and the read endpoint's normalized
output: the canonical client loop is **GET the draft → edit the returned `overview` block list → PATCH with the returned
`latest_revision_id` as the base**.

1. Add `PATCH /api/editor/posts/{id}/` on the existing detail view, authorized by Wagtail `can_edit` on the *specific*
   page (same authorization model as the read endpoint), and kept authentication-mechanism agnostic.
2. Require a base-revision token. Accept `base_revision_id` in the JSON body (an `If-Match`/ETag header carrying the
   same id may be added later as an equivalent). Before applying any change, compare it to the page's current
   `latest_revision_id`; if they differ, return `409 Conflict` with code `revision_conflict` and the metadata in
   "Conflict Detection" (`current_revision_id`, `submitted_base_revision_id`, the site's admin edit URL). A request
   without a base-revision token is a `validation_error`, not a silent overwrite.
3. Partial-update semantics: accept the same fields as create (`title`, `slug`, `visible_date`, `tags`, `categories`,
   `cover_image`, `overview`), all optional; only provided fields change, omitted fields are left untouched. A provided
   `overview` **replaces the whole `overview` section** — this stays lossless because the read endpoint round-trips the
   full block list, and block-level patching is deferred. Re-validate every provided field with slice 1's converters
   and the same field-precise error envelope.
4. Apply the changes in memory, then `save_revision(user=...)` — never mutate the live/published row directly. The
   update creates a new draft revision; it must not publish. A `slug` change is re-checked for sibling uniqueness, as
   on create.
5. Resolve the slice-1 live-row-vs-revision drift here: tags, categories, and cover image must be carried by the
   revision content (Wagtail's source of truth), not written to the live row ahead of publish, so a draft's revisions
   and live state cannot diverge. Revisit slice 1's create path for the same correctness if needed.
6. Return the same shape as create/read, with the **new** `latest_revision_id`, so the client can immediately chain
   another edit using it as the next base revision.

While implementing, also fold in the small reuse cleanup deferred from slice 1: extract the shared
existence-plus-`choose` media check (`get_choosable_image` / the audio equivalent) into one helper now that create and
update both resolve referenced media.

## Test Scenarios

- Authenticated editor can create a draft post under an editable blog and receives preview/edit URLs.
- Anonymous users and authenticated users without add permission cannot create posts.
- The API enforces authorization through Wagtail page permissions regardless of which authentication class set
  `request.user`, and a scoped token lacking the publish action cannot publish while a session-authenticated editor
  with publish permission can.
- The same API works with two different blog parents and never assumes a site-specific blog.
- Tags are created or resolved consistently with Wagtail/admin behavior.
- Existing cover image, image block, and gallery image IDs are accepted and missing image IDs return structured errors.
- A structured `overview` block list of heading, paragraph (rich-text HTML), and code blocks round-trips losslessly
  into and back out of django-cast body blocks.
- Draft creation does not publish the page by default.
- Updating with a stale `base_revision_id` returns `409 Conflict` and does not change the page.
- A `PATCH` with a matching `base_revision_id` saves a new draft revision, returns the new `latest_revision_id`, and
  leaves the page unpublished (`live` stays `false`).
- A `PATCH` updates only the fields it sends; omitted fields (title, tags, cover image, overview) are left unchanged.
- A provided `overview` on update round-trips losslessly through the read endpoint, and an updated draft can be edited
  again by chaining the returned `latest_revision_id`.
- A `PATCH` from a user without edit permission on the page is rejected, regardless of authentication class.
- A `PATCH` missing any base-revision token returns a `validation_error` (never a silent overwrite).
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

django-indieweb's IndieAuth remains available as one pluggable authentication class a site can add later (see
Authentication And Permissions), but it is not a foundation the API depends on. A thin Micropub handler may still be
added later as an additional surface purely for standard Micropub clients, separate from the agent-authoring API.

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
revocable only by hand. Because the API is authentication-mechanism agnostic, the token is not rejected outright — it is
a valid drop-in authentication class for a trusted single-user slice over HTTPS — but it is not recommended as the
production default for headless agents, where a scoped, expiring, revocable scheme such as IndieAuth is preferable.

## Open Questions

Resolved (2026-06-22):

- **Authentication for the first slice** — session authentication; the API stays authentication-mechanism agnostic and
  IndieAuth/token auth are later config-only additions (see Authentication And Permissions).
- **Body contract** — a structured `overview` block list is the canonical first-slice contract; there is no Markdown
  parser in the request path (see Body Serialization).
- **Markdown** — demoted to an optional later convenience behind an optional dependency, not part of the first slice.

Still open:

- What action→required-scope mapping should django-cast expose for scoped-token backends (a single content scope versus
  separate create/update/publish scopes)?
- What is the right endpoint namespace: `editor`, `content`, or a Wagtail-compatible extension?
- Should publish-by-request be allowed in the create endpoint for callers with publish permission, or only through a
  separate publish endpoint?
- How should remote image import be constrained so it is useful for agents but safe for production sites?

Resolved by update slice (2026-06-23):

- The first update slice accepts `base_revision_id` in the JSON body; `If-Match`/ETag support remains a later
  compatibility option.
- `PATCH` clears collection fields by sending an explicit empty list and clears the cover image by sending
  `cover_image: null`; omitted fields are left unchanged.
- Update remains `overview`-only, matching slice 1. Addressing `detail` explicitly remains a later extension.
