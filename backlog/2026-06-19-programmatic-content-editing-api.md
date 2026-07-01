# Programmatic Content Editing API

Date: 2026-06-19

Status: Slice 1 implemented (2026-06-22): `GET /api/editor/parents/`, `POST /api/editor/posts/`, and
`GET /api/editor/posts/{id}/` are shipped. The API is authentication-mechanism agnostic, authenticates with Django
session auth in the first slice, and authorizes with Wagtail page permissions. The body contract is a structured block
list (heading, paragraph, code, image, gallery).

Slice 2 implemented (2026-06-23): **updating drafts** via `PATCH /api/editor/posts/{id}/` with revision-based conflict
detection (`409`). `PATCH` requires `base_revision_id`, saves a new Wagtail draft revision, leaves omitted fields
untouched, replaces the whole `overview` section when supplied, and supports explicit `cover_image: null` to clear the
draft cover image. `If-Match` later landed as an equivalent request-header transport for the same revision token.

Slice 3 implemented (2026-06-25): **editor media uploads and full body-section editing**. The slice added authenticated
editor endpoints for listing/uploading Wagtail images, django-cast audio, and django-cast video; upload collection
discovery for `image`, `audio`, and `video`; `detail` section create/read/update support next to `overview`; and `video`
as an author-facing body block. The cumulative editor block set is now `heading`, `paragraph`, `code`, `image`,
`gallery`, `audio`, and `video`. Preflight confirmed that `Audio` and `Video` are collection-scoped, `overview` and
`detail` share the same built-in block set, and the shared pagination class uses `pageSize` with default 40 and maximum
200. Request-path media probing now goes through an editor budget helper: editor audio uploads fail with
`probe_timeout` when required probing exceeds the budget and `probe_failed` when required probing returns unusable
metadata, while video poster probing remains optional display enrichment. Audio/video editor uploads also use a per-user
one-in-flight lock with owner-token release semantics.

Slice 4 implemented (2026-06-28): **post publish action**. The slice added
`POST /api/editor/posts/{id}/publish/` for draft `Post` pages. The action requires Wagtail admin access plus page publish
permission, publishes the latest draft revision through Wagtail's revision publishing path, returns published revision
and public URL metadata, and keeps `publish: true` rejected on create/update.

Remaining follow-ups beyond slice 4 (triaged 2026-06-29 into concrete `BACKLOG.md` items instead of one broad bucket):

- **Episode draft endpoints — implemented (2026-06-29).** Draft-only `POST/GET/PATCH /api/editor/episodes/` for
  `Episode` pages under a `Podcast` parent. See "Episode Endpoints (Next Implementation Slice)" below for the detailed
  contract and shipped status.
- **Episode publish action — implemented (2026-06-30).** `POST /api/editor/episodes/{id}/publish/`
  mirrors the post publish action plus the episode-specific `podcast_audio`-required gate.
- **Rendered-preview endpoint — shaping.** Server-rendered draft preview for token-only/non-admin clients that cannot
  use the admin-session `preview_url`.
- **Scoped-token / IndieAuth scope mapping — shaping.** The generic action→required-scope mapping; see Authentication
  And Permissions and Open Questions.
- **Remote media import — shaping.** Importing media from remote URLs behind server-side safety constraints; see Open
  Questions.
- **Optional `If-Match` conflict tokens — implemented (2026-07-01).** Equivalent request-header transport for the
  existing `base_revision_id` conflict semantics; see Conflict Detection.
- **Media replacement workflows — later.** Replacing an existing media object's file versus only creating new objects;
  see Open Questions.
- **Optional Markdown convenience input — later.** An optional `*_markdown` input converted server-side into the
  canonical block list behind an optional dependency; see Body Serialization, Tier 2.
- **`embed` body block support — later.** Adding `embed` as an author-facing block once URL validation and provider
  behavior are specified; stored `embed` blocks are currently preserved only as unsupported placeholders.

## Summary

django-cast should provide a trusted, authenticated content editing API that lets external tools and agents create,
update, hand off admin preview URLs, publish posts through an explicit action, and revise posts or episodes without
direct database access or production shell access.
For the currently planned media/detail slice, preview means returning an admin-session `preview_url`; rendered preview
responses for token-only/non-admin clients remain deferred. Publishing is handled by a separate explicit post action, not
by create/update payloads.

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
- Accept a structured, round-trippable body block list instead of requiring clients to construct raw Wagtail StreamField
  internals (block IDs, storage format), and without forcing a Markdown parser into the request path. Rich-text HTML
  round-trips after Wagtail's normal normalization/sanitization.
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
  opens admin-session preview URLs, and may publish the draft.
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
- `POST /api/editor/posts/{id}/publish/`
  - Publish the latest draft revision through Wagtail's revision publishing path.
- `GET /api/editor/media/images/`
  - List Wagtail images the caller may `choose`; listing is scoped by choose permission, not upload/add permission.
    Responses use the shared pagination envelope and support the planned `q`, repeatable `tag`, and deterministic
    ordering behavior described below. This is "what the caller can reference"; image collection discovery and upload use
    the stricter "where the caller can create and then reference" predicate of `add` plus `choose`.
- `POST /api/editor/media/images/`
  - Require image `add` plus `choose`, upload a Wagtail image using existing image validation and Wagtail's configured
    image upload limit (`WAGTAILIMAGES_MAX_UPLOAD_SIZE` when configured, otherwise the byte limit the active Wagtail image
    form enforces in this installation; if no limit is discoverable, add an editor default of 10 MiB before shipping),
    and return an ID immediately usable in `cover_image`, `image`, or `gallery` references.
- `GET /api/editor/media/audios/`
  - List django-cast audio objects the caller may `choose`; listing is scoped by the audio chooser policy confirmed in
    preflight, not upload/add permission. Responses use the shared pagination envelope and support the planned `q`,
    repeatable `tag`, and deterministic ordering behavior described below.
- `POST /api/editor/media/audios/`
  - Require audio `add` plus the post-save `choose` check described below, upload a django-cast `Audio` object using
    existing form validation, `CAST_AUDIO_UPLOAD_MAX_BYTES` (effective cap chosen by preflight) for the single submitted
    audio file, and editor request-path probing bounded by a hard editor per-upload budget of
    10 seconds
    across all probes; return the ID once the post-save `choose` check passes, making it immediately usable in an `audio`
    block. Required audio probing provides saved
    duration/file metadata, so if it times out, reject the upload with HTTP 422 and code `probe_timeout` before returning
    an ID and delete any object/files saved before the timeout. `probe_timeout` is not a client-repairable validation
    error; agents should surface it or retry later according to their own policy, but they must not assume a retry will
    fix a deterministic in-cap file that always exceeds the editor probe budget. Files that consistently exceed the
    synchronous editor probe budget are unsupported by this editor upload path until a later background/async media
    pipeline exists; clients should use the Wagtail/admin or another out-of-band upload workflow for those files. Required
    probes must run before optional
    chaptermark extraction; optional extraction may use only the remaining budget, time out non-fatally, and save without
    extracted marks, matching the optional-video-poster pattern.
    Evaluate gates in this order:
    authentication/admin access, one-in-flight audio/video upload throttle, collection selection/usability,
    request/form/size validation, save plus required probing, then the post-save `choose` check. Collection usability includes the add permission predicate for at least
    one usable target; no usable target is a whole-request 403 before file validation, while multiple usable targets with
    omitted `collection` is a `collection`/`ambiguous` validation error before file validation. This ordering may require
    multiple repair cycles because collection errors are returned before file/size errors. It affects which structured
    error is returned; with ordinary multipart transport it does not avoid receiving the uploaded file body, so each repair
    cycle may require the client to resend the full file. The mitigation in this slice is collection discovery before large
    uploads; no separate metadata-only upload precheck endpoint is added. If the post-save
    `choose` check fails after successful probing, delete the saved object/files and return whole-request
    `post_save_permission_denied`/HTTP 403. The transient save-before-cleanup window is an accepted edge case for custom
    policies and timeout cleanup and must be documented/tested. Preflight must confirm synchronous upload transport can safely
    handle the target cap, including Django upload handlers, worker/request timeouts, and proxy body limits; the
    10-second probing cap does not cover file transfer time. Preflight must include concurrent upload pressure on worker
    capacity/rate limiting; if that cannot be made acceptable, reduce the cap, add throttling, or split transport work
    before shipping audio uploads. The default mitigation is an editor-upload throttle allowing one in-flight audio/video
    upload per authenticated user; a second concurrent audio/video upload for the same user returns HTTP 429 with flat code
    `rate_limited`. If preflight justifies a different throttle or a caps-only mitigation, update this PRD, the API
    reference, and tests before implementation. Preflight must also prove probing subprocesses can be interrupted at the cap and that
    partial-save cleanup removes every saved row/file on timeout. Because audio timeout is fatal, preflight must also
    prove valid files up to the effective audio size cap complete required probing within the editor timeout under
    expected load; this is a hard ship blocker. Otherwise reduce the cap or defer extraction before shipping audio uploads.
    If `CAST_AUDIO_UPLOAD_MAX_BYTES` is absent, use a target default of 64 MiB unless preflight lowers the effective cap,
    then document the chosen value in the API reference, release notes, and implementation note. If cleanup after
    `probe_timeout` fails, do not return an object ID; return
    HTTP 500 with code `cleanup_failed`, log the orphaned row/file identifiers for operators, and surface the need for
    manual cleanup rather than pretending the upload failed cleanly. `cleanup_failed` takes precedence over the original
    `probe_timeout` response when both occur; do not include orphan identifiers in the client response body.
- `GET /api/editor/media/videos/`
  - List django-cast video objects the caller may `choose`; listing is scoped by the video chooser policy confirmed in
    preflight, not upload/add permission. Responses use the shared pagination envelope and support the planned `q`,
    repeatable `tag`, and deterministic ordering behavior described below.
- `POST /api/editor/media/videos/`
  - Require video `add` plus the post-save `choose` check described below, upload a django-cast `Video` object using
    existing form validation, `CAST_VIDEO_UPLOAD_MAX_BYTES` (target default 512 MiB; deployments may raise to 2 GiB only
    after preflight confirms transport viability),
    and editor request-path poster probing bounded by a hard editor per-upload budget of 10 seconds; return the ID once
    the post-save `choose` check passes, making it immediately usable in a `video` block. Poster generation is optional
    display enrichment, so if poster
    probing times out after form validation succeeds, save without a generated poster and return `poster: null`. If the
    post-save `choose` check fails, delete the saved object/files and return whole-request
    `post_save_permission_denied`/HTTP 403; the transient save-before-cleanup window is an accepted edge case for custom
    policies and must be documented/tested.
    Evaluate gates in this order:
    authentication/admin access, one-in-flight audio/video upload throttle, collection selection/usability,
    request/form/size validation, save plus optional poster probing, then the post-save `choose` check. Collection errors are returned before file/size errors, so the same
    multiple-repair-cycle and possible large-transfer cost described for audio applies to video and must be documented in
    the API reference. The mitigation in this slice is collection discovery before large uploads; no separate metadata-only
    upload precheck endpoint is added. Video poster probing is optional display enrichment in this slice; a timeout saves
    the video without
    a generated poster and returns `poster: null`, not `probe_timeout`. If preflight discovers any required video probe in
    the request path, update this contract before implementation instead of silently mapping it to the audio timeout
    behavior. If cleanup after a failed post-save `choose` check fails, do not return an object ID; return HTTP 500 with
    code `cleanup_failed`, log the orphaned row/file identifiers for operators, and surface the need for manual cleanup.
    `cleanup_failed` takes precedence over the original `post_save_permission_denied` response when both occur; do not
    include orphan identifiers in the client response body.
    Preflight must confirm synchronous upload transport can safely handle the target cap, including Django upload
    handlers, worker/request timeouts, and proxy body limits; the 10-second probing cap does not cover file transfer
    time. Preflight must include concurrent upload pressure on worker capacity/rate limiting; if that cannot be made
    acceptable, lower the effective editor video cap, add throttling, or split transport work before shipping video
    uploads. A 2 GiB cap is an opt-in deployment target, not the shippable default for the editor endpoint. The default
    mitigation is the same one-in-flight audio/video upload throttle per authenticated user; a second concurrent audio/video
    upload for the same user returns HTTP 429 with flat code `rate_limited`. If preflight justifies a different throttle or a caps-only mitigation, update
    this PRD, the API reference, and tests before implementation. Preflight must also
    prove poster probing can be interrupted at the cap and that failed-upload cleanup removes every saved row/file.
- `GET /api/editor/media/collections/?type=image|audio|video`
  - List collections the caller may use for editor media uploads of the requested media type, returning `id`, `name`,
    display-only `breadcrumb`, and machine-readable `ancestors` as `[{ "id": ..., "name": ... }]` from root to parent.
    `breadcrumb` is generated from `ancestors` plus the collection name for UI display and is not guaranteed unique.
    For images these are collections where the caller has both `add` and `choose`; image discovery must not return
    choose-only collections that cannot accept uploads. For audio/video these are addable collections, gated by preflight
    that verifies the same audio/video chooser policy used by list/body-reference validation and verifies saved owned
    audio/video objects become choosable after `user` assignment. Preflight must also confirm `Audio` and `Video` support
    Wagtail collections; if not, redefine or drop collection discovery for those types before implementation. If any
    audio/video collection or chooser preflight fails, replace this fallback with a concrete predicate before
    implementation, such as requiring add+choose collection permission for audio/video too or disabling collection
    discovery for the affected type. If collection discovery is disabled for a type because the model is not
    collection-scoped, remove that type from the accepted `type` enum so requests such as `type=audio` or `type=video`
    return `invalid_choice`, and update that type's upload request and response contract before shipping; do not require
    non-null upload `collection` metadata for a model that has no collection relationship.
  - Upload requests accept optional multipart `collection`. If omitted, auto-select exactly one usable collection; if
    multiple are usable, return `validation_error` on `collection` with code `ambiguous`; if none are usable, return
    whole-request `no_upload_collection`/HTTP 403. For audio/video, "usable" at auto-selection time means addable; the
    saved object can still fail the post-save `choose` check and return `post_save_permission_denied`/HTTP 403 with
    cleanup. If the caller supplies a well-formed collection ID that is missing or not usable for that caller and media
    type, return HTTP 400 `validation_error` on `collection` with code `collection_permission_denied`; malformed collection values
    return `validation_error` on `collection` with code `invalid`. Whole-request upload authorization failures use `permission_denied`; submitted
    collection values that are missing or unusable use the distinct field-level code `collection_permission_denied`.

Episode endpoints (the selected next slice and its ready publish follow-up) mirror the same shape; see
"Episode Endpoints (Next Implementation Slice)" below for the detailed contract:

- `POST /api/editor/episodes/`
- `GET /api/editor/episodes/{id}/`
- `PATCH /api/editor/episodes/{id}/`
- `POST /api/editor/episodes/{id}/publish/`

The implemented create/read/update response baseline already includes `id`, `type`, `title`, `slug`, `parent`,
`visible_date`, `tags`, `categories`, `cover_image`, `overview`, `latest_revision_id`, `live`, `status`, `preview_url`,
`edit_url`, and `api_url`. The next slice must preserve those fields and extend the same response-shape parity to
`detail`. A separate preview endpoint remains deferred in the default scope for this slice because the current
assisted-authoring workflow only needs a stable URL for human review by a Wagtail admin-session user. Token-only or
non-admin clients are out of scope for this slice and cannot rely on that admin draft URL in a future auth model; the
later rendered-preview endpoint is the planned path for those clients if they need server-rendered draft HTML. Relying on
`preview_url` therefore has an explicit workflow precondition: a human reviewer can open the URL in an authenticated
Wagtail admin session. The implementation note or PR description must record that the product owner accepted this default
deferral. If they do not, stop and replan around a rendered-preview endpoint before starting the media/detail
implementation; that replan must decide whether rendered preview is added to this slice or becomes a prerequisite slice.
Until that future endpoint lands, token-only clients can create, read, and update draft source through the editor API but
cannot self-render or self-verify draft previews. The API reference must document that `preview_url` is an admin-session
URL that may redirect to login or fail for non-admin callers; it is not a token-client rendering contract.

### Why the editor API has its own read endpoints

The existing read API is not a substitute for the editor `GET` endpoints, because it serves a different audience:

- The Wagtail pages API (`GET /api/wagtail/pages/{id}/`) is `AllowAny` and, by Wagtail default, returns only live
  pages. The editor workflow produces **drafts**, which never appear there; a client cannot read back the draft it just
  created.
- It exposes raw StreamField plus rendered `html_overview`/`html_detail`, not the normalized authoring source the write
  API round-trips. Safe patching of an existing draft needs that authoring representation, not rendered HTML.
- It does not expose revision metadata such as `latest_revision_id`, which the implemented `base_revision_id` /
  `If-Match` conflict detection depends on.
- No existing endpoint lists `Blog`/`Podcast` pages filtered by the caller's add-child permission;
  `GET /api/editor/parents/` fills that gap.

The editor `GET` endpoints are therefore permission-scoped views over draft-aware, revision-aware, authoring-shaped data.
The implemented draft round-trip workflow depends on aligned create/read/update response shapes. The current baseline
response fields are the canonical 16-field baseline listed in the response example section below; this slice must
preserve those client-visible names and add `detail` without regressing response-shape parity.

## Create Post Request

The create/update API accepts structured body section block lists plus structured metadata. This slice preserves the
current `overview` requiredness confirmed in preflight on `POST /api/editor/posts/`; the expected current contract is
that `overview` remains required and `detail` is optional. If preflight finds `overview` is already optional, keep it optional
and update this planning note, tests, and API reference before implementing `detail`. `PATCH` accepts either section
independently and leaves omitted sections untouched.

This slice should enforce `publish` as an explicit guard for this API version after the compatibility preflight is
complete: `false` or an omitted field is accepted, while `true` is rejected with the editor `validation_error` envelope
on the `publish` field using code `unsupported`; the separate publish action is the only publish path in this API
version. Interpret this after normal BooleanField coercion: values that coerce to `true` take the `unsupported` path,
values that coerce to `false` are accepted, and values that cannot be coerced are normal field validation errors. The
current shipped endpoints do not publish from `publish: true`; if implementation discovers a compatible deployment that
did, treat the guard as compatibility-impacting and do not ship it until the API reference and release notes call out the
change. Malformed `publish` values fail normal field validation before the empty-update guard, so
`{base_revision_id, publish: "not-a-bool"}` returns a `publish` field error rather than `non_field_errors`/`required`.
If `overview` remains required on create, clients that only want to populate `detail` must still send `"overview": []`.
An empty `overview` list is valid when `overview` is supplied. If preflight finds `overview` is already optional, keep
  that optional create behavior instead. Preflight and tests must verify that a detail-only draft with `overview: []`
  saves and renders without breaking existing templates; if it does not, stop and update the create contract before
  implementation. Preflight and tests must also verify that an explicit empty `detail: []` renders the same user-visible
  content as an absent `detail` section. For both `overview` and `detail`, omitted means "do not touch this section" on `PATCH`; an explicitly
supplied empty list means "replace this section with an empty section." Implementers must check field presence, not
truthiness, so `[]` is never treated as omitted.

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
    {"type": "gallery", "value": [{"id": 456}, {"id": 789}]},
    {"type": "audio", "value": {"id": 321}}
  ],
  "detail": [
    {"type": "paragraph", "value": "<p>Long-form notes can be edited independently.</p>"},
    {"type": "video", "value": {"id": 654}}
  ],
  "publish": false
}
```

Media placement is expressed inline as `image`/`gallery`/`audio`/`video` blocks within each section list, so block order
is explicit rather than inferred from a separate `media` instruction stream.
`publish: false` is accepted for explicitness but is inert in this API version; clients may omit it. Publish state changes
only through the explicit publish action.

Target response after this media/detail slice:

This response example shows the current metadata/URL baseline plus the `detail` extension planned for this slice. The
concrete URL values are illustrative placeholders. The paragraph HTML happens to be unchanged after normalization in this
example; clients must still treat Wagtail's saved normalized HTML as the response value.

```json
{
  "id": 987,
  "type": "cast.Post",
  "title": "Weeknotes 2026-25",
  "slug": "weeknotes-2026-25",
  "visible_date": "2026-06-19T18:00:00+02:00",
  "cover_image": {
    "id": 456,
    "alt_text": "Notebook and laptop on a desk"
  },
  "tags": ["weeknotes"],
  "categories": [],
  "parent": {"id": 123},
  "latest_revision_id": 6543,
  "live": false,
  "status": "draft",
  "overview": [
    {"type": "heading", "value": "Notes"},
    {"type": "paragraph", "value": "<p>Shipped the first draft.</p>"},
    {"type": "code", "value": {"language": "python", "source": "print(\"hello\")"}},
    {"type": "gallery", "value": [{"id": 456}, {"id": 789}]},
    {"type": "audio", "value": {"id": 321}}
  ],
  "detail": [
    {"type": "paragraph", "value": "<p>Long-form notes can be edited independently.</p>"},
    {"type": "video", "value": {"id": 654}}
  ],
  "preview_url": "/admin/pages/987/view_draft/",
  "edit_url": "/admin/pages/987/edit/",
  "api_url": "/api/editor/posts/987/"
}
```

The current response fields to preserve in this slice are `id`, `type`, `title`, `slug`, `parent`, `visible_date`,
`tags`, `categories`, `cover_image`, `overview`, `latest_revision_id`, `live`, `status`, `preview_url`, `edit_url`, and
`api_url`. This slice adds `detail`, so create/read/update responses should serialize the editable `overview` and
`detail` sections in the same author-facing shape.

## Body Serialization

`Post.body` is a Wagtail StreamField with `overview` and `detail` sections; each section is an ordered list of typed
blocks (`heading`, `paragraph`, `code`, `image`, `gallery`, `embed`, `video`, `audio` — see
`src/cast/post_body_blocks.py`). The `paragraph` block is a `RichTextBlock` whose value is stored as HTML. The API
contract should map directly onto that block-list shape rather than onto a prose format, for two reasons:

- The primary client is an agent, which natively emits structured JSON. A structured block list is unambiguous and
  round-trippable after Wagtail's normal normalization/sanitization; a prose format like Markdown forces the server to
  *guess* the mapping (is `## X` a `heading` block or rich text inside a `paragraph`? how do nested lists/blockquotes
  flatten into paragraph HTML?).
- Safe `PATCH`/round-trip editing needs the structured representation anyway — rendered HTML cannot be reliably diffed
  and patched. Read responses must return Wagtail's saved normalized values so a client that echoes them back produces an
  idempotent content no-op under the same sanitizer/normalizer for fields and sections that already exist. If a section
  was absent and GET serializes it as `[]`, echoing that `[]` on PATCH stores that section as an explicit empty section.
  This is content-idempotent but not storage-idempotent for absent sections. Clients that are not intentionally editing a
  section should omit that section on PATCH. Building the
  structured contract first avoids a throwaway Markdown-only path.

Tier 1, implemented in the first two slices — structured `overview` block list. The third slice extends the same
contract to `detail` in Tier 1b below:

- The request supplies the `overview` section as an ordered list of `{ "type": ..., "value": ... }` blocks using
  django-cast's existing block names. Example: `{"type": "heading", "value": "Notes"}`,
  `{"type": "paragraph", "value": "<p>Shipped the first draft.</p>"}`,
  `{"type": "code", "value": {"language": "python", "source": "print('hi')"}}`.
- The server owns conversion to Wagtail StreamField values and block IDs; clients never construct raw StreamField
  internals.
- `paragraph` values are rich-text HTML, validated/sanitized through the same path Wagtail uses on admin save.
- Image and gallery blocks reference existing image IDs (see Media Handling).
- Audio blocks reference existing django-cast audio IDs.
- A read endpoint returns the same normalized block list (plus rendered values where useful) so agents can patch
  existing drafts safely.

Tier 1b, contract for the third implementation slice — structured `overview` and `detail` block lists. This is the same
media/detail slice that adds the editor media endpoints described below:

- `POST /api/editor/posts/` keeps accepting the existing `overview` field and additionally accepts an optional
  `detail` field.
- `GET /api/editor/posts/{id}/` returns both `overview` and `detail` as normalized author-facing block lists. A missing
  section returns an empty list. Adding `detail` to existing response shapes is considered an additive, backward-compatible
  response extension for current overview-only clients.
- `PATCH /api/editor/posts/{id}/` accepts `overview` and/or `detail`. Each provided section replaces that whole section;
  omitted sections are preserved exactly as stored in the current draft revision. An explicitly provided empty list clears
  that section. A GET response for an absent section serializes as `[]`; echoing that value on PATCH stores an explicit
  empty section. Omit a section on PATCH to preserve its current internal representation.
- `PATCH /api/editor/posts/{id}/` also applies the explicit `publish` guard: omitted or `false` is accepted, malformed
  values are normal field validation errors, and `true` returns the `validation_error` envelope with code `unsupported` at
  field path `publish` without publishing. A syntactically valid PATCH that only supplies the body `base_revision_id` or
  header `If-Match` token and no editable field remains a 400 `validation_error` on `non_field_errors` with code
  `required`, matching the current slice-2 behavior. `publish: false` is not an editable field for this guard, so
  `{base_revision_id, publish: false}` is still an empty update and returns `non_field_errors`/`required`;
  `publish: true` takes the explicit `publish`/`unsupported` validation path.
- Section updates must preserve the other section and any unsupported/custom top-level sections in `Post.body`.
  Unsupported/custom top-level sections may come from existing data, future settings, or downstream customizations even
  though django-cast's built-in sections are `overview` and `detail`; the editor API must not drop sections it does not
  understand.
- The same converter and validation error style is used for both sections, with error paths prefixed by `overview` or
  `detail`, after implementation verifies that the active `overview` and `detail` section definitions support the same
  built-in block set. If the section definitions differ, this slice must document and test per-section block sets before
  implementation instead of assuming a shared converter constant.
- The intended cumulative built-in author-facing block set after this slice is `heading`, `paragraph`, `code`, `image`,
  `gallery`, `audio`, and `video`; only `video` is newly API-supported by the editor converter, while `detail`
  conversion is new for every supported block type. The implementation plan gates that set behind active StreamField
  section verification. `embed` remains deferred until URL validation and provider behavior are specified.
- `image`, `gallery`, `audio`, and `video` body references must validate that each referenced media object is choosable
  by the caller, not merely that it exists. If preflight finds the shipped image/gallery/audio behavior accepted
  visible-but-not-choosable media, tightening it to `choose` is compatibility-impacting and must be called out in the API
  reference and release notes before implementation proceeds. If product review rejects that compatibility impact, replan
  this slice around the shipped looser predicate instead of silently changing behavior.
- "Unsupported" has two different levels in this section: an unsupported block type inside a submitted `overview` or
  `detail` section is rejected at that block path, while unsupported/custom top-level body sections already stored on the
  page are preserved when the API replaces a known section.
- Stored but unsupported blocks inside a supported section, such as existing `embed` blocks in `overview` or `detail`, must
  not be silently dropped. `GET` should surface them as unsupported placeholders with their stored block type and position
  so clients can preserve them during a full-section replacement. A `PATCH` that sends an unsupported placeholder back
  with the same `stored_type` and original `position` preserves the matching stored block, even when the placeholder moves
  to a different submitted index; omitting the placeholder removes that block as part of the explicit full-section
  replacement.
- Unsupported block types in either section are rejected with the existing editor `validation_error` envelope, using an
  `unsupported_block_type` code at the section-prefixed path such as `detail.0.type`.

Tier 2, later — optional Markdown convenience:

- An optional `overview_markdown` input may be added later as a convenience for human-driven or Markdown-native
  clients. It would be converted server-side into the same block list, behind an optional dependency so the Markdown
  parser is not forced onto all installs.
- This is explicitly *not* part of the first slice; the structured block list is the canonical contract.

## Media Handling

Implemented in the first two slices:

- Cover images, and inline `image`/`gallery` blocks in the `overview` list, may reference existing Wagtail image IDs.
- Inline `audio` blocks may reference existing django-cast audio IDs.
- The API validates that referenced media exists and passes the shipped media-reference permission check; the media/detail
  preflight confirms whether the shipped predicate is already `choose` or a looser visible-to-caller check.
- The response includes structured errors for missing images or invalid block values, using the block's path in the
  `overview` list (for example `overview.3.value.1.id`).

Next slice:

- Add editor-scoped media list/upload endpoints for Wagtail images, django-cast audio, and django-cast video:
  `GET/POST /api/editor/media/images/`, `GET/POST /api/editor/media/audios/`, and
  `GET/POST /api/editor/media/videos/`, plus `GET /api/editor/media/collections/?type=image|audio|video` so clients
  can discover valid `collection` IDs when auto-selection is ambiguous. Collection discovery follows the pre-upload
  portion of upload semantics: images return collections where the caller has `add` + `choose`, while audio/video return
  collections where the caller can add. The saved owned audio/video object is still checked for `choose` after upload,
  so discovery results are candidates rather than unconditional upload guarantees under custom policies. Preflight must
  verify that django-cast's stock owner policy makes saved owned audio/video objects choosable after `user` assignment;
  if not, this plan must switch audio/video discovery to a stricter permission predicate before implementation.
  Collection discovery requires `type`; a missing value is a validation error on `type` with code `required`, and any
  value other than `image`, `audio`, or `video` is a validation error on `type` with code `invalid_choice`. Besides shared
  pagination parameters, collection discovery accepts only `type`; it does not support `q` or `tag` filtering in this
  slice. Discovery results use the shared pagination envelope and items shaped as `{"id": 5, "name": "Uploads",
  "breadcrumb": "Root/Uploads", "ancestors": [{"id": 1, "name": "Root"}]}`. `breadcrumb` is display text generated from
  `ancestors` plus the collection name and is not guaranteed unique; clients that need hierarchy should use `ancestors`.
- `GET` endpoints list only objects the caller may `choose`, using the same permission policy as the corresponding
  chooser view for that media type. List responses should include enough metadata for agents to pick or display items:
  common `id`, `type`, `title`, `tags`, and nullable admin edit URL fields; image `file`, `width`, and `height`; audio
  `subtitle`, `transcript_diarization_mode`, `file_formats`, and media URL fields; and video `original` plus nullable
  `poster` fields. `transcript_diarization_mode=enabled` may appear on existing audio objects created outside this API,
  but it is read-only/legacy for this slice and cannot be echoed back to editor upload. Editor media item
  file URL fields use relative URLs consistently (`file`, `m4a`, `mp3`, `oga`, `opus`, `original`, and `poster`); if an
  existing serializer emits absolute URLs, normalize or replace it for this editor API shape. The supported media models
  in this slice all expose tags. Resolve whether each media type is collection-scoped before implementing its serializer;
  the `collection` response field is required only for collection-scoped media. Media item `type` values are model
  labels, expected to be `wagtailimages.Image`,
  `cast.Audio`, and `cast.Video` after preflight, and are intentionally distinct from body block `type` values such as
  `image`, `audio`, and `video`; clients must treat media item `type` as display/discriminator metadata and must not copy
  it into a body block. Audio media item responses intentionally do not include chaptermark readback in this slice; the
  submitted or extracted chaptermarks affect the saved object, but media list/upload responses stay focused on selection
  metadata and file URLs. Media item responses include nullable `collection` metadata so clients can confirm the upload
  destination, including when the endpoint auto-selected the only usable collection. Fresh uploads must return
  `collection: {"id": ..., "name": ...}` for collection-scoped media; legacy listed audio/video may return
  `collection: null` only if preflight confirms nullable collection rows exist. Images should not return
  `collection: null` under Wagtail's stock non-null image collection model. If preflight proves a media type is not
  collection-scoped, update that type's contract before shipping and do not promise non-null collection metadata for it.
  Audio/video collection scoping is a hard preflight blocker for the collection discovery and upload-selection contract:
  if either model is not collection-scoped, update this PRD and remove or redefine that type's discovery/upload collection
  behavior before implementation.
  For audio/video, chooser visibility intentionally follows the existing
  `CollectionOwnershipPermissionPolicy`: callers should expect their own uploaded media plus any objects the active
  policy grants them, not an unrestricted shared media library. List endpoints use
  the existing non-editor API pagination envelope by explicitly configuring the same pagination class:
  `{ "count": ..., "next": ..., "previous": ..., "results": [...] }`. The shared pagination class remains the source of
  truth for page-size parameter names, defaults, and caps; implementation tests should use the verified values rather
  than hard-coded assumptions.
- `GET` endpoints should support at least `q` search, repeatable `tag` filtering, and deterministic ordering by each
  model's creation timestamp descending, then `-id`. The expected concrete fields are intentionally different:
  `-created_at, -id` for Wagtail images and `-created, -id` for audio/video, but implementation must verify those field
  names against the active models before relying on them. `tag` filters by exact stored tag name without API-level case
  normalization; multiple `tag` parameters are ANDed, so results must have every requested tag. Clients that need to find a
  just-uploaded item by tag should filter with tag names from the upload/list response, not the pre-normalized submitted
  multipart/admin tag string. This
  keeps agents from paging through an entire media library to find a known item. Search behavior should degrade
  gracefully without depending on the configured search backend: this slice ships the deterministic database filter as the
  `q` contract rather than replacing it with backend search. In this
  slice `q` is a filter, not a ranking contract: images search `title__icontains`, audio searches `title` and `subtitle`
  with `icontains`, and video searches `title__icontains`. This DB-filter baseline is immediate and deterministic for
  freshly uploaded media. Search-backend integration can be added later only as an additive path that preserves the DB
  baseline's immediate read-after-write behavior and deterministic ordering. Image `q` search is intentionally title-only
  for this slice; exposed
  tags are handled by the separate repeatable `tag` filter. When both `q` and `tag` are present, apply them as an
  intersection on the permission-limited queryset before final ordering; filter order must not change the result set.
- Unsupported query parameters on editor media list/discovery endpoints return `validation_error` with code
  `unsupported_parameter`; collection discovery accepts only `type` plus verified shared pagination parameters. The
  accepted query-parameter set is intentionally closed for editor media endpoints, so typoed, proxy-injected, or
  forward-looking parameters fail fast instead of being silently ignored. Preflight must enumerate the full allowlist,
  including the exact shared pagination parameter names emitted in `next`/`previous` links and any framework-level
  parameters such as DRF `format` when enabled. Implementations should derive this allowlist from the configured
  pagination class and request parser/rendering stack where possible instead of hard-coding deployment-conditional names.
  Every query parameter emitted in pagination `next`/`previous` links must be accepted by the same endpoint.
- `POST` endpoints accept `multipart/form-data`, create a media object, and return `201 Created` with the same
  serialized item shape used inside the list endpoint's `results`. Clients select a destination with an optional
  multipart `collection` field containing a collection ID. If omitted, the endpoint auto-selects only when the caller has
  exactly one usable upload collection for that media type; otherwise it returns the collection errors described below.
- Invalid file, size-limit, form, non-timeout optional probing, and collection failures must be converted into the editor
  API's structured error envelopes so agents receive machine-readable repair paths rather than raw Wagtail/DRF errors.
  Required audio `probe_timeout` is the exception: it uses the flat whole-request HTTP 422 body described in "Validation
  Errors."
- Uploading requires enough permission for the returned object to be inserted by the same caller. Wagtail images require
  both `add` and `choose` permission before upload. Audio/video require `add` before upload and must pass an
  instance-level `choose` check after saving with `user=request.user`. Missing up-front media `add`/`choose` permission
  should return the editor API's structured `permission_denied` response without leaking collection contents; no usable
  upload collection is the separate `no_upload_collection` branch.
- Upload endpoints must enforce the same upload size caps as the existing model/admin paths before saving or probing
  media: Wagtail's configured image upload limit for images (`WAGTAILIMAGES_MAX_UPLOAD_SIZE` when configured, otherwise
  the active Wagtail image form limit, with an editor default of 10 MiB if no active limit is discoverable),
  `CAST_AUDIO_UPLOAD_MAX_BYTES` for audio (target default 64 MiB if absent, effective cap chosen by preflight), and
  `CAST_VIDEO_UPLOAD_MAX_BYTES` for video (target default 512 MiB; deployments may raise to 2 GiB only after transport
  preflight).
  Oversized uploads return HTTP 400 `validation_error` on the
  submitted file field, preserving the active form/validator code and message for that media type. Audio uploads accept
  exactly one of `m4a`, `mp3`, `oga`, or `opus` in this slice; multiple submitted audio
  file fields return `validation_error` on `non_field_errors` with code `too_many_files`. Implementation must verify that audio/video size
  validators run during form
  validation before `Audio.save()` or `Video.save()` triggers duration, chaptermark, or poster probing; if they do not,
  add explicit pre-save validation in the editor upload views. If `CAST_AUDIO_UPLOAD_MAX_BYTES` is missing, add
  editor-scoped pre-save validation with the documented 64 MiB target default unless preflight lowers the effective cap.
  If `CAST_VIDEO_UPLOAD_MAX_BYTES` or its validators are missing, add editor-scoped pre-save validation with the documented
  effective video cap before wiring editor uploads. Preflight must also confirm deployment
  request/proxy/time
  limits can accept the target caps, including Django upload handlers/temp-file behavior, application server request
  timeouts, and front proxy body-size/time limits; if not, reduce the editor caps or split large-upload transport work
  into a prerequisite before shipping audio/video uploads. Preflight must record how the active Wagtail image form limit
  is read; if it cannot be read, use the editor 10 MiB default above. Do not add or change shared admin/model validators
  for this slice
  unless the compatibility impact on the admin and older `POST /api/upload_video/` endpoint is documented in the API
  reference and release notes and the older endpoint's response contract is verified.
  Shipping audio/video uploads is blocked until preflight either confirms existing pre-save validators run before probing
  or adds the editor-scoped validators, and until the one-in-flight audio/video upload throttle or a documented replacement
  mitigation is implemented.
- Missing or inaccessible body media references are treated as invalid submitted object IDs and collapse to per-path
  `not_found` inside the HTTP 400 `validation_error` envelope. Upload collection failures are authorization problems for
  choosing an upload target: no usable collection for an omitted `collection` is whole-request
  `no_upload_collection`/HTTP 403, while a submitted missing or unusable `collection` is an HTTP 400 `validation_error` on the
  `collection` field with code `collection_permission_denied`. This divergence from body-reference `not_found` is deliberate and
  must not be normalized away: body references validate object IDs for insertion, while collection values authorize where
  a new upload may be created. Both choices preserve non-disclosure while keeping submitted field values in the
  validation envelope.
- Upload requests may include a `collection` ID. For Wagtail images, enumerate collections where the caller has
  `add` + `choose` for the resulting image. For audio/video, the current `CollectionOwnershipPermissionPolicy` makes the
  freshly uploaded object choosable through ownership once `user=request.user` is set, so collection selection is based
  on collections the caller may add to, followed by a defensive instance-level `choose` check on the saved object before
  returning it. Collection usability must be checked before or around form binding, or by constraining the form field to
  the already-selected collection; do not let out-of-permission collections fall through as form `invalid_choice`
  validation errors. "Usable" in the following rule means the media-type-specific definition above. If no collection is
  supplied and the caller has exactly one usable upload collection for that media type, the endpoint must use that
  collection. If the caller has no such collection, return `no_upload_collection`; if the
  caller has multiple such collections and omits `collection`, return `validation_error` on `collection` with code
  `ambiguous`. Do not silently choose a default/root collection when multiple usable collections exist; clients must use
  the collection discovery endpoint and send an explicit `collection` so uploads are deterministic and do not land in an
  unintended collection. If the caller supplies a collection ID that is missing or not usable for that caller and media
  type, return `validation_error` on `collection` with code `collection_permission_denied` so collection existence is not leaked;
  malformed collection values return `validation_error` on `collection` with code `invalid`. A well-formed but nonexistent collection ID counts as
  missing and must collapse to `collection_permission_denied`, not `not_found`, `invalid_choice`, or `does_not_exist`. The
  audio/video
  post-save `choose` check is defensive for custom or future permission policy changes; under the stock owner policy it
  should pass after owner assignment. Do not hold a database transaction open across media probing/poster generation. If
  the defensive post-save `choose` check fails, delete the object, clean up any saved files from that failed save, and
  return whole-request `post_save_permission_denied`/HTTP 403 before returning the response. A transient database or
  file-storage visibility window between save and cleanup is accepted because media probing is not wrapped in a long
  transaction. A concurrent request could theoretically observe or reference the failed object during that custom-policy
  window; this is an accepted edge case for this slice, and cleanup must happen before the failed upload response. Under
  custom policies, an addable collection discovered before
  upload may still fail this post-save chooser check; that failed upload is intentionally discarded rather than returned
  as an unusable media object. This can also happen for the auto-selected single collection case; clients cannot fix it
  by retrying another collection and need a permission/policy change. The request may already have transferred and
  probed a large file before this defensive post-save authorization failure; requiring `add` up front is the bounding
  permission check, and the wasted-transfer cost is an accepted custom-policy edge case for this slice. Clients should call
  collection discovery before large uploads whenever more than one target might exist, because this slice does not add a
  separate metadata-only upload precheck endpoint. Record product owner acceptance of that residual transfer cost in the
  implementation note or PR description.
- Wagtail image upload should reuse Wagtail's image model/form behavior where practical, set `uploaded_by_user`, respect
  collection permissions, and return an ID usable as a cover image, image block, or gallery item. The image `choose`
  permission is available in django-cast's supported Wagtail range; implementation must verify the active permission
  policy exposes it before wiring the endpoint. Supported upload fields are `title`, `file`, `tags`, and `collection`;
  `file` is required, while `title`, `tags`, and `collection` are optional subject to the collection auto-selection rule.
- Audio upload should reuse `AudioForm` and existing audio validation/duration/chapter-mark behavior. Supported upload
  fields are the existing admin form fields where applicable: `title`, `subtitle`, `transcript_diarization_mode`,
  `m4a`, `mp3`, `oga`, `opus`, `tags`, `chaptermarks`, and `collection`. `chaptermarks` is the same newline-delimited
  text field used by the admin form, with one `HH:MM:SS Title text` mark per line. Implementation must verify those
  field names against `AudioForm` before binding request data. `Audio.save()` performs duration and file-size enrichment
  synchronously; `AudioForm.save()` syncs chapter marks using admin precedence: manually supplied `chaptermarks` win, and
  ffprobe extraction is attempted only when the field is empty and an uploaded audio file changed. The view must set
  `Audio.user` to the caller before saving so owner-based chooser permissions make the uploaded audio immediately
  reusable. Exactly one of `m4a`, `mp3`, `oga`, or `opus` is required in this slice; the editor upload view should
  enforce this before form save, return `non_field_errors` with code `required` when all audio file fields are absent,
  and return `non_field_errors` with code `too_many_files` when more than one audio file field is submitted. If one audio file is submitted, run normal form
  validation so per-field upload errors such as size or content-type failures are preserved.
  Metadata fields are optional.
  `transcript_diarization_mode` is optional, defaults to `inherit`, and accepts `inherit` or `disabled`. This slice
  rejects `enabled` with the `validation_error` envelope and code `unsupported` at field path
  `transcript_diarization_mode`; accepting it is a later additive change after transcript behavior is specified.
- Video upload should use `get_video_form()` so existing video form/model validation and poster generation behavior
  match the admin. Supported upload fields are `title`, `original`, `poster`, `tags`, and `collection`. The view must set
  `Video.user` to the caller before saving so owner-based chooser permissions make the uploaded video immediately
  reusable. Implementation must verify the active `Video.create_poster()` behavior before relying on poster precedence:
  the expected behavior is that a caller-supplied `poster` wins because generation is skipped when `poster` already exists.
  Otherwise the current `Video.save()` path is expected to call poster generation synchronously. That generation may still
  leave `poster` empty when video dimensions are unavailable or ffmpeg/ffprobe fails. The response should include a poster
  URL when the supplied or generated poster exists after save, and `null` otherwise.
- Audio duration/file-size enrichment and video poster extraction run synchronously in the current model paths. This
  slice keeps that behavior only if implementation enforces a hard editor-upload request-path ffprobe/ffmpeg budget of
  10 seconds total per upload request across all probing/generation paths, including audio chaptermark extraction. The
  budget is cumulative, not 10 seconds per subprocess. Preferred implementation:
  route ffprobe/ffmpeg timeout/budget selection through a small shared helper backed by an explicitly request-local propagation
  mechanism, preferably a `contextvars.ContextVar` context manager that tracks remaining budget only after verifying all
  relevant calls run in the same request context. First inventory every request-path ffprobe/ffmpeg call site used by
  audio/video save and form save, refactor direct subprocess calls through the helper or an explicit timeout/budget
  argument, and test every call site.
  Editor upload views must wrap form save in that context or pass the remaining budget explicitly so nested `Audio.save()`,
  `Video.save()`, and form-save subprocess calls receive the editor-only budget. Tests must prove the override reaches
  those nested calls, and a mandatory negative test must fail if any editor request-path probe silently uses the
  admin/default timeout. This keeps Wagtail/admin and the older video upload endpoint on their current timeout while
  bounding editor uploads. If implementation can only add or lower bounds in shared model/form paths, treat that as a
  compatibility impact on the admin/older upload paths, document it in the API reference and release notes, and verify
  the older `POST /api/upload_video/` response contract still holds. Do not ship this slice with any request-path
  editor upload probing call left on an unbounded or admin-length timeout; if neither request-local propagation nor
  explicit remaining-budget arguments can cover every call site, split timeout hardening into a prerequisite change before
  implementing media uploads. If required audio duration/file validation exceeds the editor budget, reject the upload
  with HTTP 422 and flat code `probe_timeout` before returning an object ID; this is not a client-repairable validation error.
  Required audio duration/file probes must run before optional chaptermark extraction so optional enrichment cannot consume
  the cumulative budget first and starve required validation. If optional audio chaptermark extraction exhausts the editor budget, save without extracted marks. If video poster
  extraction exhausts the editor budget after form validation succeeds, save the video without a generated poster and
  return `poster: null`
  rather than failing an otherwise valid upload. Note the intentional timeout contrast: required audio duration/file
  probing fails the upload on timeout, while optional chaptermark and video poster enrichment degrade. Moving media
  probing/poster generation to background tasks is a later performance hardening option. Returning HTTP 422 for
  `probe_timeout` is deliberate: the file is not processable within the synchronous editor media budget, even if retry might help a
  load-sensitive near-timeout case. The API reference must state that retry can help transient load but will not fix a file
  that deterministically exceeds the synchronous editor budget. The
  10-second editor cap is intentional even though it may make immediate editor video upload responses return
  `poster: null` more often for large valid files than the admin path. For video, `original` is required; `title`,
  `poster`, `tags`, and `collection` are optional subject to the collection auto-selection rule.
- Add `video` block validation to the editor body converter. Referenced videos must be choosable by the caller, using
  django-cast's video collection ownership permission policy, and each missing/inaccessible ID must produce the same
  per-path `not_found` error shape.
- Existing/inaccessible image, gallery, audio, and video references must all use the same `not_found` collapse so the API
  never reveals whether an object exists outside the caller's permissions. Implementation must verify the current
  image/audio error code before extending the rule; if current behavior differs, align the docs and tests before changing
  it.
- Upload endpoints should keep file validation errors machine-readable under the editor error envelope where possible.
  Form errors from image/audio/video forms should be flattened to dotted paths matching the submitted field names, with
  `non_field_errors` reserved for form-wide validation such as an audio upload missing every audio-file field.
- JSON post create/update requests accept `tags` as a list of strings. Multipart media uploads accept `tags` as the same
  string input accepted by the Wagtail/admin tag widget. Implementations must rely on the existing form field/widget
  parsing rather than a naive comma split, so taggit quoting rules for spaces or commas keep working. Responses normalize
  tags to a list of strings.
- Newly uploaded media that passes the applicable post-save `choose`/visibility preflight must appear in unsearched
  chooser lists and DB-filter `q` results immediately through the database-backed list query; this visibility must not
  depend on search reindexing. Search-backend indexing and search-backed `q` visibility are deferred with backend-search
  integration.
- Keep the older `POST /api/upload_video/` endpoint working for backward compatibility. The new editor video upload
  endpoint may reuse code/validation from it, but the older endpoint keeps its current response contract unless a
  separate deprecation is planned.

Later slices:

- Import images/media from remote URLs after explicit server-side validation.
- Return generated rendition metadata when useful for non-admin preview clients.

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

Where this plan says "admin access" in endpoint gate ordering, it means the existing Wagtail admin-access permission gate
used by `EditorAPIView` (for example `wagtailadmin.access_admin`), independent of whether the request arrived through a
session, token, or future IndieAuth class. It must not be implemented as an `is_staff` or session-only shortcut.

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
- Opening the returned admin-session `preview_url` requires the corresponding Wagtail admin draft view/edit permission.
- Publishing requires publish permission for that page and must be a separate action.

The API must not rely on `is_staff` alone, and it must not assume a single blog per site.

## Drafts, Revisions, And Publishing

Creates and updates should save draft revisions by default. A request field such as `"publish": false` may be accepted
for explicitness, but publishing should not be the default behavior. In this API version, `"publish": true` is rejected
on both create and update with the `validation_error` envelope and code `unsupported` at field path `publish`; clients
must use the separate post publish action.

The post publish action publishes the latest draft revision through Wagtail's revision publishing path instead of
mutating live page fields directly. That keeps Wagtail history intact and lets django-cast hooks such as podcast episode
numbering run consistently for programmatic publishes and admin publishes.

Publish response metadata should include the published revision ID, live URL, and any model-specific side effects that
the client may need to display.

## Conflict Detection

Update requests must include a revision token: either `base_revision_id` in the JSON body or a strict `If-Match` request
header containing the same revision id as a single strong quoted integer, such as `"6543"`. If both transports are
supplied, they must match. Malformed or contradictory header values use the editor `validation_error` envelope; stale
valid tokens return `409 Conflict` with enough metadata for the client to reload and ask for human review. The editor API
does not emit response `ETag` headers or use `412 Precondition Failed` in this version; clients discover the token from
`latest_revision_id` in the JSON response.

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

Validation errors should be stable and machine-readable. The editor error envelope keeps the status mapping established by
the first slices: field/request validation errors return HTTP 400 with the
`{"code": "validation_error", "errors": ...}` envelope; whole-request permission-denied requests return HTTP 403 with a
flat `{"code": "permission_denied", "detail": ...}` shape; upload requests with no usable collection return HTTP 403 with
flat code `no_upload_collection`; post-save media chooser failures return HTTP 403 with flat code
`post_save_permission_denied`; missing top-level editor resources such as
`/api/editor/posts/{id}/` return HTTP 404 with flat `not_found`; revision conflicts return HTTP 409 with the conflict
metadata shape; throttled uploads return HTTP 429 with flat code `rate_limited`; cleanup failures after failed media saves
return HTTP 500 with flat code `cleanup_failed`; and required audio probing timeouts return HTTP 422 with flat code
`probe_timeout`. The 422 `probe_timeout` response is a flat whole-request body, not a `validation_error` envelope.
Missing or inaccessible body media object IDs submitted
inside a request body, such as media references, remain field-level HTTP 400 validation errors. Per-field
`permission_denied` and `not_found` codes inside a `validation_error` envelope still use HTTP 400 because they are
validation failures for submitted values. Upload `collection` IDs intentionally do not follow the body media `not_found`
rule: a supplied missing or unusable collection returns `collection`/`collection_permission_denied` so existence and usability are
not distinguished. Neutral media-reference `not_found` message changes for already-shipped
image/audio references must be documented in the API reference and release notes unless message text is explicitly
declared non-contractual there.

```json
{
  "code": "validation_error",
  "errors": {
    "title": [{"code": "required", "message": "This field is required."}],
    "parent": [{"code": "permission_denied", "message": "You cannot add posts under this page."}],
    "overview.3.value.1.id": [{"code": "not_found", "message": "Referenced media is not available."}]
  }
}
```

Additional editor validation examples introduced by the media/detail slice. These are a catalog of independent error
shapes from different endpoints, not one response that can occur as a single request result:

```json
{
  "code": "validation_error",
  "errors": {
    "publish": [{"code": "unsupported", "message": "Publishing is not supported by this endpoint."}],
    "detail.0.type": [{"code": "unsupported_block_type", "message": "Unsupported block type."}],
    "collection": [{"code": "ambiguous", "message": "Select a collection."}],
    "overview.0.value.id": [{"code": "not_found", "message": "Referenced media is not available."}],
    "q": [{"code": "unsupported_parameter", "message": "Unsupported query parameter."}]
  }
}
```

Query-parameter validation errors use the bare parameter name as the error key, matching `type` on collection discovery.
The `q` unsupported-parameter example is for endpoints such as collection discovery where `q` is not supported; media
list endpoints support `q`.
Existing tests that asserted older existence-specific `not_found` messages should move to the neutral "Referenced media is
not available." message when this slice updates the error text. That generic media wording is canonical for image, audio,
and video body references in this slice.

```json
{
  "code": "validation_error",
  "errors": {
    "collection": [{"code": "collection_permission_denied", "message": "You cannot upload to that collection."}],
    "non_field_errors": [{"code": "too_many_files", "message": "Submit exactly one audio file."}]
  }
}
```

The API should prefer precise field paths over broad failure messages so an agent can repair a request without guessing.
`non_field_errors` is the reserved key for validation failures that apply to the submitted request as a whole rather than
to one concrete field path.
Flat `cleanup_failed` responses include a human-readable `detail` for the caller, but orphaned row/file identifiers are
logged for operators instead of returned to the client.

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
conversion module, structured error envelope, media-reference permission checks, and the read endpoint's normalized
output; the media/detail preflight records whether those shipped checks were already `choose` or a looser visible check.
The canonical client loop is **GET the draft → edit the returned `overview` block list → PATCH with the returned
`latest_revision_id` as the base**.

1. Add `PATCH /api/editor/posts/{id}/` on the existing detail view, authorized by Wagtail `can_edit` on the *specific*
   page (same authorization model as the read endpoint), and kept authentication-mechanism agnostic.
2. Require a base-revision token. Accept `base_revision_id` in the JSON body or an `If-Match` header carrying the same id
   as a strict quoted integer. Before applying any change, compare it to the page's current `latest_revision_id`; if they
   differ, return `409 Conflict` with code `revision_conflict` and the metadata in "Conflict Detection"
   (`current_revision_id`, `submitted_base_revision_id`, the site's admin edit URL). A request without a base-revision
   token is a `validation_error`, not a silent overwrite.
3. Partial-update semantics for the implemented slice-2 contract: accept the same fields as create (`title`, `slug`,
   `visible_date`, `tags`, `categories`, `cover_image`, `overview`), all optional; only provided fields change, omitted
   fields are left untouched. `parent` is intentionally immutable on `PATCH`; moving a post between parents is out of
   scope. The media/detail slice supersedes this field list by adding `detail` and the explicit `publish` guard described
   in the media/detail request contract. A provided
   `overview` **replaces the whole `overview` section**; the read endpoint round-trips the full normalized block list,
   and block-level patching is deferred. Re-validate every provided field with slice 1's converters and the same
   field-precise error envelope.
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

## Third Implementation Slice

Status: Implemented 2026-06-25.

Let a client create and revise complete post bodies with uploaded or existing media, without requiring a prior manual
Wagtail admin media upload. This slice deliberately kept publishing, episode pages, remote import, scoped-token auth,
Markdown input, and rendered-preview endpoints out of scope; publishing landed later as the explicit post publish action.

1. Add editor media list/upload endpoints for Wagtail images, django-cast audio, and django-cast video:
   `GET/POST /api/editor/media/images/`, `GET/POST /api/editor/media/audios/`, and
   `GET/POST /api/editor/media/videos/`.
2. Reuse the established Wagtail/admin media creation paths as much as possible:
   Wagtail image form/model behavior for images, `AudioForm` for audio, and `get_video_form()` behavior for video.
   Preserve existing upload validation, audio duration/file enrichment, video poster generation, tags, owner, and
      collection behavior. Video poster generation is optional display enrichment in this slice; no video timeout returns
      `probe_timeout` unless preflight discovers a required video probe and this PRD is updated first. Poster-generation
      failures that are not required validation failures save the video with `poster: null`.
   For audio/video, the API view must set the model's `user` owner to `request.user` before saving; ModelForms do not
   assign that owner by themselves.
3. Enforce media permissions consistently:
   `GET` uses `choose`; image upload requires `add` and `choose` up front; audio/video upload requires `add` up front
   plus a post-save instance `choose` check after owner assignment; body references require `choose`. Collapse
   missing/inaccessible body media object IDs into `not_found` so object existence is not leaked across collections.
   Upload collection errors use the split defined above: no usable collection is whole-request
   `no_upload_collection`/HTTP 403, supplied unusable or missing `collection` is field-level
   `collection_permission_denied`/HTTP 400, and omitted `collection` with multiple usable targets is
   `ambiguous`/HTTP 400.
4. Add the default one-in-flight audio/video upload throttle per authenticated user, returning HTTP 429 with flat code
   `rate_limited` for a second concurrent audio/video upload by the same user. Prefer a cache-backed lock with a timeout
   long enough to cover expected request body transfer plus the request-path probe budget, not just the 10-second probe
   budget, while still expiring stale locks after worker crashes. Release the lock on every success and failure path. If
   Step 0 selects a different mechanism, update this PRD, docs, and tests before implementation.
5. Add `video` as a supported body block in the author-facing converter, with the same ID-reference shape as `audio`:
   `{"type": "video", "value": {"id": 123}}`.
   Implementation must verify the active `video` block stores a bare media ID like `audio` before relying on this
   internal value shape; this is a hard preflight blocker for video block implementation. The built-in `Post.body` block
   definitions already include `video`; this step adds API conversion and permission validation for that existing block
   type.
6. Generalize body-section handling from `overview`-only to `overview` plus `detail`. `POST` accepts optional `detail`;
   `GET` returns both sections; `PATCH` can replace either section independently while preserving omitted sections and
   any unsupported/custom top-level sections.
7. Keep the first two slices' draft/revision semantics unchanged: create and update save Wagtail draft revisions,
   return the new `latest_revision_id`, never publish, and continue to require a revision token for `PATCH`.
8. Update `docs/reference/api.rst`, the current release notes file, and this planning note when the slice is
   implemented. The API reference and release notes must explicitly call out the neutral media-reference `not_found`
   message/error-collapse behavior if this slice changes existing image or audio reference error text. At the time of
   writing the current release file is `docs/releases/0.2.61.rst`; verify it against `pyproject.toml` and the first
   entry in `docs/releases/index.rst` before editing.
   The API reference must also prominently document the collection error split: no usable upload collection is
   whole-request `no_upload_collection`/HTTP 403, while a supplied unusable or missing collection is field-level
   `collection_permission_denied`/HTTP 400 on `collection`. It must document ambiguous omitted collection separately as a
   related collection validation error with code `ambiguous`. It must also call out any visible-to-choosable permission
   tightening for already-shipped image/audio body references, not only neutral message changes. The API reference must
   also explicitly document `rate_limited`/HTTP 429, `cleanup_failed`/HTTP 500, and `probe_timeout`/HTTP 422.

## Episode Endpoints (Next Implementation Slice)

Status: draft create/read/update implemented (2026-06-29): `POST /api/editor/episodes/`,
`GET /api/editor/episodes/{id}/`, and `PATCH /api/editor/episodes/{id}/` for `Episode` pages under a `Podcast` parent.
Episodes reuse the post body converter, media-reference `choose` checks, `base_revision_id` conflict detection, and the
draft-only `publish` guard, and add the episode-specific fields (`podcast_audio`, `episode_number`, `episode_type`,
`season`, `keywords`, `explicit`, `block`). A non-podcast parent and a foreign-podcast `season` return structured
errors, and `GET /api/editor/parents/` now points podcasts at the episode create endpoint. The episode **publish**
action later landed as `POST /api/editor/episodes/{id}/publish/` with the episode-specific `podcast_audio` gate.

This slice brings posts' create/read/update/publish surface to podcast episodes. It is the closest parity follow-up
after the post editor API and reuses almost all of it; the new work is the episode-specific fields, the `Podcast`
parent requirement, and the publish-time `podcast_audio` rule.

### Why episodes are a small delta over posts

`Episode` is a concrete subclass of `Post` (see `src/cast/models/pages.py`). It shares `Post.body`
(`overview`/`detail`), tags, categories, cover image, `visible_date`, slug, and Wagtail draft/revision semantics, so the
existing body converter, media-reference `choose` checks, `base_revision_id` conflict detection, draft-only `publish`
guard, and structured error envelopes carry over unchanged. `Episode.parent_page_types = ["cast.Podcast"]`, and
`GET /api/editor/parents/` already lists podcasts the caller may add to. The implementer should preflight whether to add
dedicated `/api/editor/episodes/` views (mirroring the post views) or to generalize the existing post views; dedicated
episode views are the expected default because the parent constraint, extra fields, and publish validation differ.

### Episode-specific fields

Beyond the inherited post fields, an episode adds (all defined on `Episode` in `src/cast/models/pages.py`):

- `podcast_audio`: a single `cast.Audio` reference. Serialize/accept it as `{"id": <audio id>}` (or `null` to clear on
  `PATCH`), validated as choosable by the caller using the same audio `choose` check used by body `audio` blocks; an
  inaccessible/missing id collapses to the neutral `not_found` shape. It is **optional on a draft** (the model field is
  null/blank) and only **required at publish time** (see below).
- `episode_number`: optional positive integer (`MinValueValidator(1)`). Preserve the existing podcast publishing
  metadata behavior (manual numbers stay authoritative; opt-in automatic first-publish numbering still applies).
- `episode_type`: optional, one of `full`, `trailer`, `bonus`, or blank (blank omits the feed tag, equivalent to full).
- `season`: optional `cast.Season` reference that **must belong to the parent podcast** (matches `Episode.clean`); a
  foreign-podcast season is a structured `season` validation error.
- `keywords`: optional iTunes keyword string.
- `explicit`: choice (`1` yes, `2` no, `3` clean), default `1`.
- `block`: boolean, default `False` (block from iTunes).

### Decisions to pin in preflight

- **Response field set.** Confirm which of the iTunes/publishing-metadata fields (`keywords`, `explicit`, `block`,
  `episode_number`, `episode_type`, `season`) the episode response exposes, and confirm the shared post fields keep
  response-shape parity. The expected default is to expose all episode fields above so a client can round-trip a draft.
- **`podcast_audio` read shape.** Confirm it serializes as `{"id": ..., ...}` consistent with `cover_image`/`audio`
  blocks rather than a bare id.
- **Endpoint routing.** Confirm dedicated `/api/editor/episodes/` views versus generalizing the post views, and confirm
  the parent-type guard rejects a `cast.Blog` parent with a structured `parent` error.

### Draft create/read/update

- `POST /api/editor/episodes/`: create a draft `Episode` under a caller-selected `Podcast`. Reject a non-`Podcast`
  parent. Accept the inherited post fields plus the episode-specific fields above. Stay draft-only: reject `publish:
  true` with the existing `validation_error`/`unsupported` guard.
- `GET /api/editor/episodes/{id}/`: return editable metadata, normalized `overview`/`detail`, revision metadata, admin
  URLs, and the episode-specific fields.
- `PATCH /api/editor/episodes/{id}/`: require a revision token, preserve omitted fields/sections, support clearing
  `podcast_audio`/`season` with explicit `null`, and keep the empty-update guard. `parent` stays immutable, like posts.

### Publish action (ready follow-up)

- `POST /api/editor/episodes/{id}/publish/`: mirror the post publish action — publish the latest draft revision through
  Wagtail's revision publishing path, require Wagtail admin access plus page publish permission, and return published
  revision id and public URL metadata — plus the episode rule that **publishing requires a non-null `podcast_audio`**
  (matches `CustomEpisodeForm.clean`). A publish request for an episode without `podcast_audio` is rejected with a
  structured error (expected default: a publish-time `validation_error` on `podcast_audio`) and leaves the episode
  unpublished; do not surface a 500.
- Compatibility note: because `Episode` is a `Post`, the shipped `POST /api/editor/posts/{id}/publish/` resolves an
  episode row via `.specific` and would currently publish it without the `podcast_audio` gate. This slice must close
  that gap — either route episodes to the episode publish endpoint and enforce the gate, or enforce the episode
  validation on the shared publish path — so a podcast-audio-less episode cannot be published through the editor API.

### Done-when

- An authenticated editor can create, read back, and revise a draft `Episode` under a podcast they may add to, with
  episode-specific fields round-tripping through create/read/update.
- Foreign-podcast `season`, inaccessible `podcast_audio`, and a `cast.Blog` parent return structured errors; `publish:
  true` is rejected on create/update.
- A draft episode with `podcast_audio` publishes through Wagtail's revision path and returns publish metadata; without
  `podcast_audio` it is rejected and stays unpublished, and the post publish path cannot bypass that gate for episodes.
- Tests cover the above, and `docs/reference/api.rst` plus the current release notes document the episode endpoints.

## Test Scenarios

- Authenticated editor can create a draft post under an editable blog and receives preview/edit URLs.
- Anonymous users and authenticated users without add permission cannot create posts.
- The API enforces authorization through Wagtail page permissions regardless of which authentication class set
  `request.user`, and this API version rejects `publish: true` on create/update even when a session-authenticated editor
  has Wagtail publish permission.
- The same API works with two different blog parents and never assumes a site-specific blog.
- Tags are created or resolved consistently with Wagtail/admin behavior.
- Existing cover image, image block, and gallery image IDs are accepted and missing image IDs return structured errors.
- Uploaded image/audio/video media can be referenced immediately in a create or update request by ID.
- Media upload endpoints reject unauthenticated users, image uploads missing `add` or `choose`, and audio/video uploads
  missing `add` or failing the defensive post-save instance `choose` check.
- Media upload endpoints reject oversized files before save/probing using the existing image/audio/video size caps.
- Media upload without any usable collection returns whole-request `no_upload_collection`/HTTP 403; supplied missing or
  unusable `collection` returns field-level `collection_permission_denied`/HTTP 400; omitted `collection` with multiple
  usable targets returns `ambiguous`/HTTP 400.
- Collection discovery requires `type`, rejects invalid `type` values, returns only upload-usable collections for the
  requested media type, and uses the shared pagination envelope.
- Media list endpoints include only media the caller may choose.
- Media list endpoints apply DB-filter `q`, repeatable ANDed `tag` filters, and deterministic creation-time ordering.
- Media list/discovery endpoints reject unsupported query parameters while accepting every pagination parameter they emit.
- Throttled media uploads return HTTP 429 with code `rate_limited`.
- Required audio probing timeouts return HTTP 422 with code `probe_timeout`, delete any saved object/files, and do not
  return an object ID.
- Cleanup failure after a failed media save returns HTTP 500 with code `cleanup_failed`, does not return an object ID, and
  logs the orphaned row/file identifiers for operator cleanup. If cleanup fails after `probe_timeout` or
  `post_save_permission_denied`, `cleanup_failed` is the response code.
- Video blocks resolve existing video IDs, reject missing/inaccessible video IDs, and round-trip through read/update.
- A structured `overview` block list of heading, paragraph (rich-text HTML), and code blocks round-trips after Wagtail's
  normal rich-text normalization/sanitization into and back out of django-cast body blocks.
- A structured `detail` block list round-trips after Wagtail's normal rich-text normalization/sanitization alongside
  `overview`.
- An explicit empty `detail: []` and an absent `detail` section render the same user-visible content.
- Stored unsupported blocks inside `overview` or `detail` are visible as unsupported placeholders on read, and clients can
  preserve those blocks by sending the placeholders back with the same `stored_type` and original `position` on section
  replacement.
- Draft creation does not publish the page by default.
- `POST` or `PATCH` with `publish: true` returns `validation_error` on `publish` with code `unsupported` and does not
  publish the page.
- Updating with a stale `base_revision_id` returns `409 Conflict` and does not change the page.
- A `PATCH` with a matching body `base_revision_id` or `If-Match` revision token saves a new draft revision, returns the
  new `latest_revision_id`, and leaves the page unpublished (`live` stays `false`).
- A `PATCH` updates only the fields it sends; omitted fields (title, tags, cover image, overview, detail) are left
  unchanged.
- A provided `overview` on update round-trips through the read endpoint after Wagtail's normal rich-text
  normalization/sanitization, and an updated draft can be edited again by chaining the returned `latest_revision_id`.
- A provided `detail` on update replaces only the `detail` section and preserves the existing `overview`.
- A provided `overview` on update replaces only the `overview` section and preserves the existing `detail`.
- A `PATCH` that updates `overview` or `detail` preserves unsupported/custom top-level body sections it did not understand.
- A `PATCH` from a user without edit permission on the page is rejected, regardless of authentication class.
- A `PATCH` missing any base-revision token returns a `validation_error` (never a silent overwrite).
- Publishing uses Wagtail revision publishing and respects publish permissions.
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

Still open (each remaining content-editing follow-up is now tracked as a concrete `BACKLOG.md` item; see the triaged
list near the top of this PRD and the "Episode Endpoints (Next Implementation Slice)" section):

- ~~What action→required-scope mapping should django-cast expose for scoped-token backends (a single content scope
  versus separate create/update/publish scopes)?~~ **Resolved (2026-06-30):** two logical scopes `write`/`publish`
  (reads scope-free), enforced by a generic `HasEditorScope` permission class reading a per-method `required_scopes`
  mapping (so mixed `GET`/`PATCH` views resolve per method) against a configurable `CAST_EDITOR_SCOPES` mapping;
  session auth and unscoped tokens fall back to pure Wagtail permissions; scope failures return a 403
  `insufficient_scope`. See
  [2026-06-30-editor-api-scoped-token-auth.md](2026-06-30-editor-api-scoped-token-auth.md). Implemented in 0.2.61
  (`HasEditorScope` + `CAST_EDITOR_SCOPES`).
- What is the right endpoint namespace: `editor`, `content`, or a Wagtail-compatible extension? The shipped surface uses
  `editor`; this question is now informational rather than blocking.
- Future-only publish question: this API version rejects `publish: true`; should a later version allow
  publish-by-request in the create endpoint for callers with publish permission, or keep publishing only on explicit
  action endpoints?
- How should remote image import be constrained so it is useful for agents but safe for production sites? Tracked as
  "Editor API remote media import" (shaping).
- Should media upload endpoints support replacing existing media files, or only create new media objects? Tracked as
  "Editor API media replacement workflows" (later).
- Do token-only/non-admin editor clients need a server-rendered draft preview? **Resolved (2026-07-01):** yes;
  implemented in 0.2.61 as `GET /api/editor/posts/{id}/preview/` and
  `GET /api/editor/episodes/{id}/preview/`, returning full themed `text/html` for callers with edit permission.

Resolved by update slice (2026-06-23):

- The first update slice accepted `base_revision_id` in the JSON body; `If-Match` support later landed as an equivalent
  request-header transport.
- `PATCH` clears collection fields by sending an explicit empty list and clears the cover image by sending
  `cover_image: null`; omitted fields are left unchanged.
- Update remained `overview`-only in that slice; this is superseded by the 2026-06-25 media/detail planning below.

Resolved by media/detail planning (2026-06-25):

- The next implementation slice should edit both `overview` and `detail`; omitted sections remain untouched and
  provided sections replace the whole section; an explicit `[]` stores an empty section, and omitted sections preserve the
  existing representation.
- The next implementation slice should add create-only editor media list/upload endpoints for images, audio, and video;
  media replacement remains deferred.
- A dedicated rendered-preview endpoint was later implemented in 0.2.61. The existing admin-session `preview_url`
  remains in create/read/update responses for human Wagtail-admin review, and token-only clients can use
  `GET /api/editor/posts/{id}/preview/` or `GET /api/editor/episodes/{id}/preview/` for server-rendered draft HTML.
- Markdown input is deferred. Structured JSON remains the canonical write contract for now.
