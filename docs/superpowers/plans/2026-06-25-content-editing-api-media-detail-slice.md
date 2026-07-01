# Programmatic Content Editing API - Media And Detail Slice

Date: 2026-06-25

Status: Implemented

Implementation note: landed 2026-06-25. Preflight confirmed the planned body-section, collection, ordering, and
pagination assumptions. Audio/video probing now uses an editor request-path budget helper; editor audio upload required
probe timeouts return `probe_timeout`, required probe failures return `probe_failed`, and video poster generation remains
optional display enrichment.

Goal: extend the editor API so trusted clients can upload/select images, audio, and video; insert those media objects
into post bodies; and create/read/update both `overview` and `detail` StreamField sections while preserving Wagtail draft
revision semantics.

Out of scope for this slice: publishing, episode endpoints, scoped-token auth/enforcement, remote media import, Markdown
input, rendered-preview endpoints, `embed` blocks, replacing existing media files, and `If-Match`/ETag conflict tokens.

Planning risk: bounded ffprobe/ffmpeg probing may become prerequisite work rather than an implementation detail of this
slice. If preflight finds request-path audio/video probing cannot be capped without a broad shared-path refactor, pause
media upload implementation and land that timeout hardening first. If Step 0 invalidates several core assumptions at
once, split this plan before implementation rather than silently narrowing behavior during the change. The media portion
of this slice is therefore not a fixed implementation commitment until Step 0 completes.

## Existing Baseline

- `GET /api/editor/parents/`, `POST /api/editor/posts/`, and `GET/PATCH /api/editor/posts/{id}/` exist.
- `PATCH` requires `base_revision_id` and saves a new Wagtail draft revision.
- The built-in `Post.body` block definitions already include `video`, but the editor body converter currently handles
  `overview` only and supports `heading`, `paragraph`, `code`, `image`, `gallery`, and `audio`.
- Image references use Wagtail image `choose` permission.
- Audio references use django-cast's collection ownership policy.
- Video uploads already exist at `POST /api/upload_video/`, but that endpoint is older, returns only a bare ID, and is
  not integrated with the editor API error/permission/serialization contract.

## Target API

### Body Sections

`POST /api/editor/posts/`:

- Preserves the verified current `overview` requiredness. The expected first-slice contract is that `overview` is still
  required, but if Step 0 proves it is already optional, keep it optional and update the docs/tests to match.
- When `overview` is required, accepts `overview: []`; clients that only want to populate `detail` must still send that
  empty list.
- Adds optional `detail`.
- Saves both supplied sections into the first draft revision.

`GET /api/editor/posts/{id}/`:

- Returns `overview` and `detail` as normalized author-facing block lists.
- Returns an empty list for a missing section.

`PATCH /api/editor/posts/{id}/`:

- Accepts optional `overview` and optional `detail`.
- `overview` must remain optional on `PostUpdateSerializer`; omitted `overview` preserves the existing section.
- Replaces each supplied section wholesale.
- Treats an explicitly supplied empty list as a replacement with an empty section.
- Preserves omitted sections and any unsupported/custom top-level body sections.
- Implementations must check field presence, not truthiness; `[]` is a supplied value.
- A syntactically valid PATCH that only supplies `base_revision_id` and no editable field remains a 400
  `validation_error` on `non_field_errors` with code `required`, matching the current slice-2 behavior. `publish: false`
  is not an editable field for this guard; `publish: true` takes the explicit `publish`/`unsupported` path. Malformed
  `publish` values fail normal field validation before the empty-update guard.
- Keeps requiring `base_revision_id`.

Supported author-facing block types after this slice:

```json
[
  {"type": "heading", "value": "Notes"},
  {"type": "paragraph", "value": "<p>Rich text.</p>"},
  {"type": "code", "value": {"language": "python", "source": "print('hi')"}},
  {"type": "image", "value": {"id": 1}},
  {"type": "gallery", "value": [{"id": 1}, {"id": 2}]},
  {"type": "audio", "value": {"id": 3}},
  {"type": "video", "value": {"id": 4}}
]
```

### Editor Media Endpoints

Add routes under `src/cast/api/urls.py`:

- `GET /api/editor/media/images/`
- `POST /api/editor/media/images/`
- `GET /api/editor/media/audios/`
- `POST /api/editor/media/audios/`
- `GET /api/editor/media/videos/`
- `POST /api/editor/media/videos/`
- `GET /api/editor/media/collections/?type=image|audio|video`

`GET` endpoints:

- Require authentication and Wagtail admin access through `EditorAPIView`.
- "Wagtail admin access" means the existing permission gate used by `EditorAPIView`, not a session-only or `is_staff`
  shortcut; token-based auth classes still work when they supply an authenticated user with the required permissions.
- Reject callers without Wagtail admin access with whole-request `permission_denied`/HTTP 403.
- List only media the caller may `choose`.
- Audio/video chooser visibility intentionally follows the existing owner-based collection permission policy: callers
  should expect their own uploaded media plus any objects the active policy grants them, not an unrestricted shared media
  library.
- Set the same pagination class used by existing non-editor list APIs and use this envelope for all three media lists:
  `{ "count": ..., "next": ..., "previous": ..., "results": [...] }`.
- Include enough metadata to select or display results.
- Support `q` search, repeatable `tag` filtering, and deterministic ordering. `tag` filters by exact stored tag name
  without API-level case normalization; multiple `tag` parameters are ANDed, so results must have every requested tag.
  Clients that need to find a just-uploaded item by tag should filter with tag names from the upload/list response, not
  the pre-normalized submitted multipart/admin tag string.
  Order by each model's creation timestamp descending, then `-id`; the expected concrete fields are intentionally
  different (`-created_at, -id` for images and `-created, -id` for audio/video), but Step 0 must verify them first. In
  this slice `q` is a deterministic database filter, not a ranking or search-backend contract: images search
  `title__icontains`, audio searches `title` and `subtitle` with `icontains`, and video searches `title__icontains`.
  Search-backend integration is deferred. The database-filter baseline is immediate and deterministic, including for
  freshly uploaded media. Image `q` search is intentionally title-only for this slice; exposed tags are handled by the
  separate repeatable `tag` filter. When both `q` and `tag` are present, apply them as an intersection on the
  permission-limited queryset before final ordering; filter order must not change the result set.
- Unsupported query parameters on media list and collection discovery endpoints return `validation_error` with code
  `unsupported_parameter`; do not silently ignore typos such as `tags=` or unsupported discovery filters such as `q=`.
  The accepted parameter set is intentionally closed, so proxy-injected or future parameters will also fail until the API
  explicitly supports them. Preflight must enumerate the full allowlist, including the exact shared pagination parameter
  names emitted in `next`/`previous` links and any framework-level parameters such as DRF `format` when enabled. Derive
  the allowlist from the configured pagination class and request parser/rendering stack where possible instead of
  hard-coding deployment-conditional names. Every query parameter emitted in pagination `next`/`previous` links must be
  accepted by the same endpoint.

Collection discovery endpoint:

- Requires authentication and Wagtail admin access through `EditorAPIView`.
- Requires a `type` query parameter with one of `image`, `audio`, or `video`.
  The singular enum values are intentional even though the media list routes use plural path segments.
- Missing `type` returns `validation_error` on `type` with code `required`; any other value returns `validation_error`
  on `type` with code `invalid_choice`.
- Returns the usable upload collections for that media type using the pre-upload portion of the collection-resolution
  policy used by uploads.
  For `image`, this means collections where the caller has `add` + `choose`. For `audio` and `video`, this means
  collections where the caller can add; after upload, the saved owned object is still defensively checked for `choose`.
  Under a patched/custom permission policy, discovery can list an addable audio/video collection whose saved object later
  fails the defensive post-save `choose` check; upload still returns `post_save_permission_denied` in that case. Document
  in the API reference that discovery results are candidates, not an unconditional upload guarantee under custom policies.
- If the caller has no usable collections for the requested type, return `200 OK` with an empty `results` list; discovery
  is not a permission oracle beyond the caller's own usable set. Clients should treat empty discovery results as "no
  upload target is available"; an upload without a usable collection will still return `no_upload_collection`.
- Uses the same pagination envelope and shared page-size parameter/default/cap as media lists. Besides those shared
  pagination parameters, discovery accepts only `type`; it does not support `q` or `tag` filtering in this slice.
  Upload auto-selection counts the full usable collection set, not just the current discovery page; clients that receive
  `ambiguous` may need to page through collection discovery to see all candidates.
- Orders collections deterministically by the Wagtail/treebeard collection model `path` field, then `id`; if that model
  field is unavailable, use `name`, then `id` and update this plan/tests during preflight.
- Response items include `id`, `name`, display-only `breadcrumb`, and machine-readable `ancestors` as
  `[{ "id": ..., "name": ... }]` from root to parent. Build `breadcrumb` from `ancestors` plus the collection name; it is
  not guaranteed unique.

`POST` endpoints:

- Require authentication and Wagtail admin access through `EditorAPIView`.
- Require enough permission for the returned object to be inserted by the same caller. Images require `add` and `choose`
  before upload. Audio/video require `add` before upload and a defensive instance-level `choose` check after saving with
  `user=request.user`.
- Reject callers without Wagtail admin access with whole-request `permission_denied`/HTTP 403.
- Accept `multipart/form-data`.
- Enforce the default one-in-flight audio/video upload throttle per authenticated user for audio/video POST endpoints.
  A second concurrent audio/video upload by the same user returns HTTP 429 with flat code `rate_limited`. Prefer a
  combined per-user cache-backed lock covering both audio and video uploads. Its TTL must cover expected request body
  transfer plus the request-path probe budget, not just the 10-second probe budget, while still expiring stale locks after
  worker crashes. Release the lock on every success and failure path; if Step 0 selects a different mechanism, update this
  plan, PRD, docs, and tests before implementation.
- Return `201 Created` with the same item shape used inside the corresponding list endpoint's `results`.
- Flatten form validation errors into the editor API `validation_error` envelope.
- Use the existing editor error status mapping: validation errors are HTTP 400, whole-request permission failures are
  HTTP 403, missing editor resources are HTTP 404, and revision conflicts remain HTTP 409, plus media-upload statuses
  below: `probe_timeout`/HTTP 422, `rate_limited`/HTTP 429, and `cleanup_failed`/HTTP 500. Per-field
  `collection_permission_denied` and `not_found` codes inside a validation envelope still use HTTP 400.
- Missing or inaccessible body media references collapse to per-path `not_found` inside the HTTP 400 validation envelope
  because they are invalid submitted object IDs. Upload collection problems authorize the upload target: no usable
  collection for an omitted `collection` is whole-request `no_upload_collection`/HTTP 403, but
  a submitted missing or unusable `collection` is an HTTP 400 `validation_error` on `collection` with code
  `collection_permission_denied`. This body-reference-versus-upload-target distinction is deliberate and must not be
  normalized away. A well-formed but nonexistent
  collection ID is treated as missing and must also collapse to `collection_permission_denied`, not a not-found or invalid-choice
  error.
- Enforce existing upload size caps before saving or probing media: Wagtail's configured image upload limit for images
  (`WAGTAILIMAGES_MAX_UPLOAD_SIZE` when configured, otherwise the active Wagtail image form limit discovered during
  preflight, with an editor default of 10 MiB if no limit is discoverable),
  `CAST_AUDIO_UPLOAD_MAX_BYTES` for audio (target default 64 MiB if absent, effective cap chosen by preflight), and
  `CAST_VIDEO_UPLOAD_MAX_BYTES` for video (target default 512 MiB; deployments may raise to 2 GiB only after transport
  preflight).
  Oversized uploads return HTTP 400 `validation_error` on the submitted file field, preserving the active form/validator
  code and message for that media type.
- Accept an optional `collection` ID. For images, collection resolution must use collections where the caller can both
  upload and immediately insert the result. For audio/video, collection resolution must use collections the caller may
  add to, then verify the saved owned object is choosable before returning it. If omitted and the caller has exactly one
  usable collection for that media type, use that collection. "Usable" means the media-type-specific definition above.
  If the caller has no such collection, return
  `no_upload_collection`; if the caller has multiple such collections and omits `collection`, return `validation_error` on
  `collection` with code `ambiguous`. Collection usability must be checked before or around form binding, or by
  constraining the form field to the already-selected collection; do not let out-of-permission collections fall through
  as form `invalid_choice` validation errors. Compute the usable collection set once per upload request and reuse it for
  auto-selection and supplied-collection validation. Do not silently choose a default/root collection when multiple
  usable collections exist; clients must use the collection discovery endpoint and send an explicit `collection` so
  uploads are deterministic and do not land in an unintended collection.

Recommended response shapes, showing editable objects. `edit_url` remains nullable whenever the caller can choose a
media object but cannot edit/change it:

```json
{
  "id": 1,
  "type": "wagtailimages.Image",
  "title": "Desk photo",
  "file": "/media/original_images/desk.jpg",
  "width": 1600,
  "height": 900,
  "collection": {"id": 7, "name": "Blog media"},
  "tags": ["weeknotes"],
  "edit_url": "/admin/images/1/"
}
```

```json
{
  "id": 3,
  "type": "cast.Audio",
  "title": "Episode audio",
  "subtitle": "Interview mix",
  "transcript_diarization_mode": "inherit",
  "file_formats": "mp3 m4a",
  "mp3": "/media/cast_audio/episode.mp3",
  "m4a": "/media/cast_audio/episode.m4a",
  "oga": null,
  "opus": null,
  "collection": {"id": 7, "name": "Podcast media"},
  "tags": ["podcast"],
  "edit_url": "/admin/castaudio/3/edit/"
}
```

```json
{
  "id": 4,
  "type": "cast.Video",
  "title": "Demo clip",
  "original": "/media/cast_videos/demo.mp4",
  "poster": "/media/cast_videos/poster/poster.jpg",
  "collection": {"id": 7, "name": "Video media"},
  "tags": ["demo"],
  "edit_url": "/admin/castvideo/4/edit/"
}
```

Use relative URLs for editor media item file fields (`file`, `m4a`, `mp3`, `oga`, `opus`, `original`, and `poster`) so
agents do not need per-media-type URL rules. Do not reuse existing serializers that emit absolute media URLs unless this
editor API shape normalizes them. Pagination `next`/`previous` links may remain absolute if that is what the shared
pagination class emits; this media-field-relative/pagination-link-default split is an accepted limitation of reusing the
shared pagination class. URL shapes above are examples; implementations should use `reverse()` for configured admin
routes. `edit_url` is nullable and should be returned only when the caller may edit/change that media object in the
admin. Media item `type` values are model labels (`wagtailimages.Image`, `cast.Audio`, `cast.Video`) and are distinct
from author body block `type` values (`image`, `audio`, `video`); do not feed the media item `type` into body block
serialization. The example paths are illustrative; use route reversal for the actual admin routes (`wagtailimages:edit`,
`castaudio:edit`, and `castvideo:edit`). The image admin route shape differs from the custom audio/video route shape;
the image example intentionally omits an `/edit/` segment because implementations must use
`reverse("wagtailimages:edit")` rather than infer the path shape. That asymmetry is intentional. The current
`Video.save()` path is expected to call poster generation synchronously unless a poster
already exists; caller-supplied posters therefore win over generated posters only if Step 0 confirms `Video.create_poster()`
skips generation when `poster` is set. Video `poster` may still be `null` in the immediate upload response if no poster file
  was supplied, video dimensions were unavailable, or ffmpeg/ffprobe failed. The examples show editable objects; image
  upload/list responses may still return `edit_url: null` when the caller can add/choose but not edit/change. Under the
stock owner policy, freshly uploaded audio/video created with `user=request.user` should return a non-null `edit_url`
when the policy exposes the expected `change` check. List responses or custom policies may still return
`edit_url: null` for objects the caller may choose but not edit/change. The audio `file_formats` field intentionally
mirrors the existing `Audio.file_formats` string property; the response should also include `subtitle` and the exact
audio URL fields `m4a`, `mp3`, `oga`, and `opus`, with `null` for formats that are not present. `file_formats` is kept
as a legacy convenience string for compatibility with the model property; clients should prefer the explicit per-format
URL fields for machine decisions. `transcript_diarization_mode` reports the stored field value, not a resolved
transcript policy. Existing audio objects created outside this editor API may report `enabled`, but editor audio uploads
reject `enabled` in this slice and clients cannot echo that value back into the upload endpoint. `collection` reports the
saved object's collection so clients can confirm the upload destination. Fresh
upload responses must include `collection` with `id` and `name`; listed legacy media may use `collection: null` only if
preflight confirms nullable collection rows exist. Media item `collection` intentionally includes only `id` and `name`;
collection discovery uses the richer
`id`/`name`/`breadcrumb`/`ancestors` shape.

## Permission Model

Images:

- Reuse `wagtail.images.permissions.permission_policy`.
- The image `choose` permission is available in django-cast's supported Wagtail range; verify the active permission
  policy exposes it before wiring the endpoint.
- `GET` filters with `image_permission_policy.instances_user_has_permission_for(user, "choose")` or the Wagtail 7
  equivalent if the policy API name changes.
- `POST` requires `user_has_permission(user, "add")` and `user_has_permission(user, "choose")`.
- Use the permission policy's collection-permission query, not just the global boolean, when deciding whether the caller
  has zero, one, or multiple `add` + `choose` collections.
  The collection query is the source of truth: passing the global `add`/`choose` gate but having no `add` + `choose`
  collection still returns `no_upload_collection`.
- Created images should set `uploaded_by_user` and respect Wagtail collection form behavior.
- Accepted upload fields are `title`, `file`, `tags`, and `collection`.
- `file` is required; `title`, `tags`, and `collection` are optional subject to collection auto-selection.
- Enforce Wagtail's configured image upload size limit before saving. Use `WAGTAILIMAGES_MAX_UPLOAD_SIZE` when configured;
  otherwise use the active Wagtail image form limit discovered during preflight.
- `tags` uses the same string input accepted by the Wagtail admin tag widget; use the existing form field/widget parsing
  rather than a naive comma split so taggit quoting rules keep working.
- Uploads may include a `collection` ID. If no collection is supplied and the caller has exactly one `add` + `choose`
  collection, use it. If the caller has no `add` + `choose` collection, return `no_upload_collection`; if the caller has
  multiple such collections and omits `collection`, return `validation_error` on `collection` with code `ambiguous`.
- If the caller supplies a collection ID that is missing or not an `add` + `choose` collection for that caller, return
  HTTP 400 `validation_error` on `collection` with code `collection_permission_denied` so collection existence is not leaked;
  malformed collection values return `validation_error` on `collection` with code `invalid`.
  Perform that collection-usability check before binding the image form, or constrain the form field to the selected
  collection, so an out-of-permission collection does not surface as a field `invalid_choice` validation error.

Audio:

- Reuse `CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")`.
- `GET` uses `instances_user_has_permission_for(user, "choose")`.
- `POST` requires `add` before upload and an instance-level `choose` check after saving with `Audio.user` set.
- Use collections the caller may add to when deciding whether the caller has zero, one, or multiple usable upload
  collections. Because `CollectionOwnershipPermissionPolicy` makes freshly uploaded owned audio choosable after
  `Audio.user` is set, verify the saved object with `user_has_permission_for_instance(user, "choose", audio)` before
  returning it instead of assuming audio `choose` is collection-scoped. This post-save check is defensive for custom or
  future permission policy changes; under the stock owner policy it should pass after owner assignment. Do not hold a
  database transaction open across audio probing. If the defensive post-save `choose` check fails, delete the object,
  clean up any saved files from that failed save, and return whole-request `post_save_permission_denied`/HTTP 403 before
  returning the response. Cleanup must cover every audio file field saved during the failed attempt: `m4a`, `mp3`,
  `oga`, and `opus`. A transient database or file-storage visibility window between save and cleanup is accepted because
  audio probing is not wrapped in a long transaction. Under custom policies,
  an addable collection selected before upload may still fail this post-save chooser check; discard the failed upload
  rather than returning an unusable object. This can also happen for the auto-selected single collection case; clients
  cannot resolve it by retrying another collection.
- Creation should use `AudioForm` so upload validation, chapter-mark syncing, tags, and collection behavior match the
  admin. `Audio.save()` performs duration and file-size enrichment synchronously; `AudioForm.save()` syncs manual or
  extracted chapter marks.
- The API view must instantiate `Audio(user=request.user)` before binding the form. `AudioForm` does not assign the
  owner itself, and owner assignment is what makes the uploaded object immediately choosable under the collection
  ownership policy.
- Accepted upload fields are `title`, `subtitle`, `transcript_diarization_mode`, `m4a`, `mp3`, `oga`, `opus`, `tags`,
  `chaptermarks`, and `collection`; verify these names against `AudioForm` before binding request data. `chaptermarks`
  is the same newline-delimited text field used by the admin form, with one `HH:MM:SS Title text` mark per line.
- Chaptermark precedence matches `AudioForm`: manually supplied `chaptermarks` win, and ffprobe extraction is attempted
  only when the field is empty and an uploaded audio file changed.
- Exactly one of `m4a`, `mp3`, `oga`, or `opus` is required in this slice; metadata fields are optional.
- If none of the four audio file fields is submitted, return `non_field_errors` with code `required` before saving. If
  more than one is submitted, return `non_field_errors` with code `too_many_files`. If exactly one audio file is
  submitted, run normal `AudioForm` validation so per-field upload errors such as size or content-type failures are
  preserved before duration or chaptermark probing.
- `transcript_diarization_mode` is optional, defaults to `inherit`, and accepts `inherit` or `disabled`. This slice
  rejects `enabled` with the `validation_error` envelope and code `unsupported` at field path
  `transcript_diarization_mode`; accepting it is a later additive change after transcript behavior is specified.
- Enforce `CAST_AUDIO_UPLOAD_MAX_BYTES` for the single submitted audio file through the existing audio validators before
  duration probing. Multi-format batch upload is deferred.
- `tags` uses the same string input accepted by the Wagtail admin tag widget; use the existing form field/widget parsing
  rather than a naive comma split so taggit quoting rules keep working.
- Uploads may include a `collection` ID. If no collection is supplied and the caller has exactly one usable add
  collection, use it. If the caller has no usable add collection, return `no_upload_collection`; if the caller has multiple
  usable add collections and omits `collection`, return `validation_error` on `collection` with code `ambiguous`.
- If the caller supplies a collection ID that is missing or not a usable add collection for that caller, return HTTP 400
  `validation_error` on `collection` with code `collection_permission_denied` so collection existence is not leaked; malformed
  collection values return `validation_error` on `collection` with code `invalid`.
  Perform that collection-usability check before binding the form, or constrain the form field to the selected
  collection, so an out-of-permission collection does not surface as a field `invalid_choice` validation error.

Video:

- Reuse `CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")`.
- `GET` uses `instances_user_has_permission_for(user, "choose")`.
- `POST` requires `add` before upload and an instance-level `choose` check after saving with `Video.user` set.
- Use collections the caller may add to when deciding whether the caller has zero, one, or multiple usable upload
  collections. Because `CollectionOwnershipPermissionPolicy` makes freshly uploaded owned video choosable after
  `Video.user` is set, verify the saved object with `user_has_permission_for_instance(user, "choose", video)` before
  returning it instead of assuming video `choose` is collection-scoped. This post-save check is defensive for custom or
  future permission policy changes; under the stock owner policy it should pass after owner assignment. Do not hold a
  database transaction open across poster generation. If the defensive post-save `choose` check fails, delete the object,
  clean up any saved files from that failed save, and return whole-request `post_save_permission_denied`/HTTP 403 before
  returning the response. Cleanup must cover the uploaded `original`, a supplied `poster`, and any generated poster
  file written during the failed attempt. A transient database or file-storage visibility window between save and cleanup
  is accepted because poster generation is not wrapped in a long transaction. Under custom policies, an addable
  collection selected before upload may still fail this post-save chooser check;
  discard the failed upload rather than returning an unusable object. This can also happen for the auto-selected single
  collection case; clients cannot resolve it by retrying another collection.
- Creation should use `get_video_form()` so validation, tags, collection behavior, and poster generation match the
  admin.
- The API view must instantiate `Video(user=request.user)` before binding the form. The form does not assign the owner
  itself, and owner assignment is what makes the uploaded object immediately choosable under the collection ownership
  policy.
- Accepted upload fields are `title`, `original`, `poster`, `tags`, and `collection`.
- `original` is required; `title`, `poster`, `tags`, and `collection` are optional subject to collection auto-selection.
- Enforce `CAST_VIDEO_UPLOAD_MAX_BYTES` through the existing video validators before poster generation.
- `tags` uses the same string input accepted by the Wagtail admin tag widget; use the existing form field/widget parsing
  rather than a naive comma split so taggit quoting rules keep working.
- Caller-supplied `poster` wins over generated poster extraction only after Step 0 confirms the active
  `Video.create_poster()` skips generation when `poster` is already set. If no poster is supplied, the current model save
  path is expected to attempt poster generation synchronously.
- Uploads may include a `collection` ID. If no collection is supplied and the caller has exactly one usable add
  collection, use it. If the caller has no usable add collection, return `no_upload_collection`; if the caller has multiple
  usable add collections and omits `collection`, return `validation_error` on `collection` with code `ambiguous`.
- If the caller supplies a collection ID that is missing or not a usable add collection for that caller, return HTTP 400
  `validation_error` on `collection` with code `collection_permission_denied` so collection existence is not leaked; malformed
  collection values return `validation_error` on `collection` with code `invalid`.
  Perform that collection-usability check before binding the form, or constrain the form field to the selected
  collection, so an out-of-permission collection does not surface as a field `invalid_choice` validation error.
- Keep the older `POST /api/upload_video/` endpoint working with its current response contract. The editor video upload
  endpoint may share validation/helper code with it, but changing or deprecating the older route is out of scope.

Body references:

- `image`, `gallery`, `audio`, and `video` blocks require `choose` permission for each referenced object.
- Missing and inaccessible IDs must produce the same per-path `not_found` error for every media type so collection
  membership is not leaked. Verify current image/audio behavior first; this slice extends the verified rule to video.
- Unknown block types inside submitted `overview` or `detail` are rejected at the block path. Unknown/custom top-level
  sections already stored in `Post.body` are different: preserve them when replacing a known section.
- Stored but unsupported blocks inside a supported section, such as existing `embed` blocks, must not be silently dropped.
  Read responses should surface them as unsupported placeholders with stored block type and position. Replacing a section
  can preserve one of these blocks when the client sends the placeholder back with the same stored block type and original
  position, even if the placeholder moves to a different submitted index; omitting the placeholder removes that block as
  part of the full-section replacement.

## Implementation Steps

0. Verify implementation preconditions before changing behavior.
   - Confirm the active Wagtail image permission policy exposes image `choose`.
   - Confirm `overview` is currently required on `PostCreateSerializer`; if it is already optional, update this plan
     before treating required `overview` as request-contract stability and preserve the existing optional behavior.
   - Confirm explicit empty `detail: []` renders the same user-visible content as an absent `detail` section.
   - Confirm create/read/update responses preserve the current 16-field baseline (`id`, `type`, `title`, `slug`,
     `parent`, `visible_date`, `tags`, `categories`, `cover_image`, `overview`, `latest_revision_id`, `live`, `status`,
     `preview_url`, `edit_url`, and `api_url`) while adding `detail`.
   - Confirm admin route names used for media `edit_url` reversal: `wagtailimages:edit`, `castaudio:edit`, and
     `castvideo:edit`. If any route differs, update this plan and examples before implementing serializers.
   - Confirm `preview_url` is documented as an admin-session review URL, not a rendered preview for token-only or
     non-admin clients. The implementer and product owner for this feature must explicitly accept in the PR description
     or implementation note that previewing remains out-of-band for agent callers in this slice; otherwise stop and add
     a rendered-preview endpoint to the scope before implementation.
   - Confirm existing create/update behavior for `publish: true`, including whether `PATCH` currently accepts, ignores,
     or rejects a `publish` field. This slice still rejects `publish: true` on both create and update with the
     `validation_error` envelope and code `unsupported` at field path `publish`; the preflight decides whether that
     enforcement is additive or compatibility-impacting. If either endpoint currently publishes or otherwise treats
     `publish: true` as
     successful, stop and document the backward-compatibility impact before changing it; do not ship the guard until the
     API reference and release notes call out the change.
   - Confirm current image and audio reference errors already collapse missing and inaccessible IDs to `not_found`; if
     not, align docs/tests before extending the rule to video.
   - Confirm media ordering fields first because list tests depend on them: image `created_at`, audio/video `created`,
     and common `id`. If any field differs, update this plan and tests before implementing media lists.
   - Confirm collection discovery ordering fields before writing tests: expected order is Wagtail/treebeard `path`, then
     `id`; if `path` is unavailable, use `name`, then `id` and update this plan/tests.
   - Confirm image/audio/video expose tags in the active models/forms and that response serializers can return a stable
     list of tag names.
   - Confirm `Audio.file_formats` exists and returns the intended legacy space-delimited string before exposing it in
     editor audio responses.
   - Confirm whether image/audio/video collection fields can be null on legacy rows. If any can be null, keep
     `collection` nullable for list responses and update tests; fresh uploads must still return a non-null collection.
   - Enumerate the full query-parameter allowlist for media list/discovery endpoints, including the exact shared
     pagination parameter names emitted in `next`/`previous` links and framework-level parameters such as DRF `format`
     when enabled. Every parameter emitted in pagination links must be accepted by the endpoint that emitted it.
   - Confirm accepted image/audio/video form field names, especially `transcript_diarization_mode` and `chaptermarks`.
   - Keep `transcript_diarization_mode=enabled` rejected with the `validation_error` envelope and code `unsupported` at
     field path `transcript_diarization_mode` in this slice.
   - Confirm whether `AudioForm` already enforces the at-least-one-audio-file constraint. If it does, reuse its
     `non_field_errors` shape; if it does not, add the view-level pre-save check without duplicating form errors.
   - Confirm active upload size settings and defaults: Wagtail image max upload size (`WAGTAILIMAGES_MAX_UPLOAD_SIZE`
     when configured, otherwise the active Wagtail image form limit discovered during preflight, with an editor default
     of 10 MiB if no limit is discoverable), `CAST_AUDIO_UPLOAD_MAX_BYTES` using a 64 MiB target default when absent and
     the effective cap chosen by preflight,
     and `CAST_VIDEO_UPLOAD_MAX_BYTES` using a 512 MiB target default unless deployment transport preflight raises or
     lowers the effective cap. If `CAST_AUDIO_UPLOAD_MAX_BYTES` is absent, add editor-scoped pre-save validation with the documented
     64 MiB target default unless Step 0 lowers the effective cap. If `CAST_VIDEO_UPLOAD_MAX_BYTES` or its validators are
     absent, add editor-scoped pre-save validation with the
     documented effective video cap before implementing editor video uploads. Do not add or change shared admin/model validators
     unless the compatibility impact on admin and the older `POST /api/upload_video/` endpoint is documented and that
     endpoint's response contract is verified.
   - Confirm audio/video upload size validators run during form validation before `Audio.save()` or `Video.save()`
     triggers duration, chaptermark, or poster probing; if they do not, add explicit pre-save validation in the editor
     upload views.
   - Confirm `Post.body` still stores independently addressable top-level `overview` and `detail` sections before
     relying on replace-one-section-and-preserve-the-rest behavior.
   - Confirm the active `overview` and `detail` section block definitions both support the cumulative built-in block set
     in this plan: heading, paragraph, code, image, gallery, audio, and video. If the section block sets differ, use
     per-section validation constants and update this plan/tests instead of sharing one body block set.
   - Confirm the active `video` body block stores the same bare-ID value shape planned below.
   - Confirm `Video.create_poster()` skips generation when `poster` is already set, so caller-supplied posters win.
   - Confirm audio/video upload collection selection should be based on addable collections plus owner-based
     instance-level `choose` after saving, not on a collection-scoped `choose` grant.
   - Confirm image/audio/video policies support `change` permission for `edit_url`; if audio/video cannot expose an
     enumerable `change` queryset, use per-object checks for the paginated page and for upload responses.
   - Confirm the shared pagination class still caps page size. The shared class is the source of truth; current
     expectation is query parameter `pageSize`, default size 40, and maximum size 200. If verified names or values
     differ, update this plan and tests to the verified values before implementation.
   - Keep search-backend reindexing out of scope for this slice; `q` uses the database-filter baseline.
   - Confirm audio/video duration/poster/chaptermark processing uses a cumulative editor-upload request-path subprocess
     budget of 10 seconds total per upload request across all probing paths, not 10 seconds per subprocess. First inventory
     every request-path ffprobe/ffmpeg call site used by audio/video save and form save. Preferred implementation: route
     timeout/budget selection through a small shared helper backed by an explicitly request-local propagation mechanism,
     preferably a `contextvars.ContextVar` context manager that tracks remaining budget only after verifying the calls
     remain in the same request context; otherwise pass the remaining budget explicitly. Editor upload views must wrap form
     save in that context or pass the budget so nested `Audio.save()`, `Video.save()`, and form-save subprocess calls
     receive the editor-only budget. If the only practical implementation changes shared
     model/form paths, treat that as a compatibility impact, document the admin/older-endpoint effect, and verify the
     older `POST /api/upload_video/` response contract still holds. If neither request-local propagation nor explicit
     budget arguments can cover every call site, split timeout hardening into a prerequisite before implementing media
     uploads. The 10-second editor cap is intentional even though it may make immediate editor video upload responses
     return `poster: null` more often for large valid files than the admin path.

1. Refactor body section helpers.
   - Replace `_overview_value()` with a generic section lookup helper.
   - Replace `_body_sections_with_overview()` with a helper that can replace any supported section.
   - Preserve unsupported/custom top-level sections. These may come from existing data, future settings, or downstream
     customizations even though django-cast's built-in sections are `overview` and `detail`.
   - Add unit tests before changing behavior.

2. Add `detail` serializer fields and view handling.
   - Preserve the Step 0 result for `PostCreateSerializer.overview`: keep it required only if it is currently required;
     if it is already optional, leave it optional. `detail` is optional in either case.
   - `PostCreateSerializer.detail = serializers.ListField(required=False)`.
   - Keep `PostUpdateSerializer.overview` optional.
   - `PostUpdateSerializer.detail = serializers.ListField(required=False)`.
   - Keep or add the explicit `publish: true` guard on both create and update: `false` or omitted is accepted, malformed
     values are normal field validation errors, and `true` returns `validation_error` on `publish` with code
     `unsupported`. Apply this after normal BooleanField coercion: values that coerce to `true` are unsupported, values
     that coerce to `false` are accepted, and values that cannot be coerced are normal field validation errors. If
     `PATCH` does not currently parse `publish`, add a write-only update field solely to reject `true` and accept
     `false`/omitted. Step 0 decides whether this is additive or compatibility-impacting; if existing clients could
     successfully send `publish: true`, document the compatibility impact before making this change.
   - Keep omitted-section semantics consistent: create omits `detail` from `Post.body` when it is not supplied, and
     update preserves an existing `detail` when it is not supplied. Serialization still returns `detail: []` for a
     missing section. Adding `detail` to response shapes is treated as an additive response extension for overview-only
     clients. If a missing section is read as `[]` and echoed back on PATCH, store an explicit empty section; clients
     should omit sections they do not intend to edit.
   - Use field-presence checks such as `"detail" in validated_data`, never truthiness, so `detail: []` clears/replaces
     the section instead of being treated as omitted. The same applies to `overview: []`.
   - Create and serialize `detail` in `PostCreateView` and `PostDetailView`.
   - Patch should replace supplied `overview` and/or supplied `detail`.

3. Add video block conversion.
   - Add `get_choosable_video()` and `video_choosable_by()` alongside image/audio helpers.
   - Verify the active `overview` and `detail` section definitions include the cumulative built-in block set before
     using one shared validation constant. If a future setting ever allows removing built-ins, fail with a clear
     validation error before writing invalid StreamField data.
   - Verify the active `video` block stores a bare media ID like the `audio` block before relying on the planned
     internal value shape.
   - Rename `SUPPORTED_OVERVIEW_BLOCKS` to a section-neutral name such as `SUPPORTED_BODY_BLOCKS`, then add `video`, only
     if Step 0 confirms `overview` and `detail` share the same block set. Otherwise keep per-section constants.
   - Convert author `{"type": "video", "value": {"id": ...}}` to Wagtail `{"type": "video", "value": id}`.
   - Round-trip stored video blocks back to the author-facing shape.
   - Reject unsupported author-facing block types in either `overview` or `detail` with `validation_error` and
     `unsupported_block_type` at paths like `detail.0.type`.
   - Add read/patch handling for stored-but-unsupported blocks inside supported sections: read as unsupported placeholders,
     and preserve a stored unsupported block when the client sends the placeholder back with the same stored block type
     and original position.

4. Add media serializers/helpers.
   - Keep them in `src/cast/api/editor/serializers.py` unless the file becomes too large; then split
     `src/cast/api/editor/media.py`.
   - Add serializer/helper functions for Wagtail images, audio, and video response shapes.
   - Reuse existing `AudioSerializer` / `VideoSerializer` only if their shape and URL behavior fit the editor API; media
     file URL fields in editor responses must be relative across image, audio, and video.
   - Include `collection: {"id": ..., "name": ...}` in all three media response shapes.
   - Include the stored `transcript_diarization_mode` field value in audio responses.
   - Include `tags` in all three media response shapes. Empty tags should serialize as an empty list, not be omitted.
   - Implement a single `can_edit_media_object(user, obj)`-style helper for final `edit_url` decisions and use it for
     upload responses and as the fallback for list responses. For lists, optimize only the candidate set feeding that
     helper where possible: build the page of chooseable results, compare those page IDs to an enumerable change/edit
     permission queryset or policy result set, and return `null` for objects the caller cannot edit. If a policy cannot
     express edit permission as an enumerable queryset, fall back to the same per-object helper for the paginated page.
     Use the `change` permission name for all three media policies.
   - For upload responses, compute `edit_url` with the shared direct instance-level edit/change permission helper on the
     created object; do not use the list-page comparison recipe for the single-object POST path.
   - Add coverage that list and upload `edit_url` calculations agree for the same object and caller when both paths can
     observe that object.

5. Harden synchronous media probing.
   - Treat bounded audio/video probing as implementation work, not just a preflight observation.
   - Inventory every request-path ffprobe/ffmpeg subprocess used for duration, chaptermark extraction, size, or poster
     generation before choosing the propagation mechanism.
   - Add the timeout/budget helper described in preflight if no suitable helper already exists. Prefer a
     `contextvars.ContextVar` context manager only if tests prove the nested model/form save calls remain in the same
     request context; otherwise pass an explicit remaining-budget value through the shared helper/API used by those call
     sites.
   - Refactor any direct subprocess call sites through the helper or explicit-budget API, then verify the editor upload
     request path has a cumulative 10-second budget rather than separate 10-second call budgets.
   - Add a test double around the subprocess helper proving the editor-upload budget set by the view is observed inside
     the nested audio/video save path.
   - Add a mandatory negative timeout test or assertion proving an uninstrumented request-path probing call would fail
     the suite rather than silently using the admin/default timeout.
   - Add timeout coverage or test doubles that prove malformed media cannot hang the upload view indefinitely.
   - Required audio duration/file probing timeout returns HTTP 422 with flat code `probe_timeout`, not a 400 validation error;
     required audio probes must run before optional chaptermark extraction so optional enrichment cannot consume the
     cumulative budget first. Optional chaptermark extraction and video poster generation degrade without failing the
     upload. HTTP 422 is deliberate because the file is not processable within the synchronous editor media budget, even if
     retry might help a load-sensitive near-timeout case. If Step 0 discovers a required video probe, update the PRD and
     this plan before implementing instead of silently mapping it to the audio timeout behavior.
   - Add an HTTP-level test for `probe_timeout` that proves failed required audio probing deletes saved rows/files before
     returning the 422 response.
   - Add a cleanup-failure branch: if object/file cleanup after `probe_timeout` or failed post-save `choose` fails, return
     HTTP 500 with code `cleanup_failed`, do not return an object ID, and log the orphaned row/file identifiers for
     operators. `cleanup_failed` takes precedence over the original `probe_timeout` or `post_save_permission_denied`
     response, and orphan identifiers stay in logs rather than the client body.
   - Add an HTTP-level test for the default one-in-flight audio/video upload throttle per authenticated user; a second
     concurrent audio/video upload for the same user returns HTTP 429 with code `rate_limited`. If Step 0 replaces that throttle
     with a caps-only mitigation or different limits, update this plan, the PRD, docs, and tests before implementation.
   - Add tests proving the throttle lock is released after successful uploads and after `probe_timeout`,
     `post_save_permission_denied`, validation errors, and `cleanup_failed` responses.
   - If the timeout hardening cannot be completed without a shared-path compatibility change, split that hardening into a
     prerequisite or document the admin/older-endpoint impact; do not ship editor uploads with any unbounded or
     admin-length request-path probing call. Accept the documented custom-policy transient visibility window only after
     confirming cleanup occurs before any failed-upload response.

6. Add editor media views and routes.
   - Use `EditorAPIView` for the same authentication/error handling as post editing.
   - Use `MultiPartParser` / `FormParser` for upload views if DRF does not select them automatically in tests.
   - Implement the `q`, repeated `tag`, and deterministic ordering pipeline specified in the target API section.
   - Add the media collection discovery endpoint using the same usable-collection calculation as upload auto-selection.
   - Reject unsupported query parameters on media list and collection discovery endpoints with `validation_error` and
     code `unsupported_parameter`.
   - Convert Django form errors into `EditorValidationError` with dotted field names, preserving `non_field_errors` as
     the reserved key for form-wide validation.
   - Ensure newly uploaded media appears in unsearched chooser lists through the database-backed list query without
     depending on search reindexing.
   - Do not add search-backend reindexing in this slice. The upload response ID, unsearched media list, and DB-filter
     `q` baseline are the guaranteed immediate-use paths for freshly uploaded media.

7. Update documentation.
   - Update `docs/reference/api.rst` with the new media endpoints, `detail`, and `video` block support. Explicitly
     document that collection discovery with no usable collections returns `200 OK` with empty `results`, while an upload
     without any usable collection target returns whole-request `no_upload_collection`/HTTP 403.
     Also document that discovery candidates, including the auto-selected single collection, are not upload guarantees
     under custom policies.
     Document that `transcript_diarization_mode=enabled` is rejected by editor audio uploads in this slice.
     Include an error status/scope table that distinguishes HTTP 400 `validation_error` envelopes from flat whole-request
     error bodies such as `permission_denied`, `no_upload_collection`, `post_save_permission_denied`, `not_found`, `rate_limited`,
     `cleanup_failed`, and `probe_timeout`.
     Make `non_field_errors` the reserved key for validation failures that apply to the submitted request as a whole.
     For collection errors, document the distinct codes: no usable upload collection is whole-request
     `no_upload_collection`/HTTP 403, while supplied unusable/missing collection is field-level
     `collection_permission_denied`/HTTP 400 on `collection`.
     Document ambiguous omitted collection separately as a related collection validation error with code `ambiguous`.
     Explicitly document the neutral media-reference `not_found` message/error-collapse behavior if this slice changes
     existing image or audio reference error text; the canonical body-reference message is "Referenced media is not
     available." for image, audio, and video.
     Document that `q` recall/freshness beyond the database-filter baseline is not guaranteed when a deployment uses a
     search backend integration in a later slice.
     Mark media `edit_url` examples as placeholders generated by route reversal, not literal URL templates for clients
     to hardcode.
     Make the verified `overview` create-time requiredness prominent. If `overview` remains required, include the
     `overview: []` requirement for clients that only want to populate `detail`; if it is already optional, document that
     preserved optional behavior instead.
   - If preflight finds that `publish: true` was previously tolerated, call out the new field-level `validation_error`
     envelope with code `unsupported` at field path `publish` in the release notes as a compatibility-impacting guard.
   - Update the current release notes file. At the time of writing this is `docs/releases/0.2.61.rst`; verify against
     `pyproject.toml` and the first entry in `docs/releases/index.rst` before editing.
   - Update `backlog/2026-06-19-programmatic-content-editing-api.md` status after implementation.
   - Update `BACKLOG.md` status if the slice changes what remains.

8. Review and verification.
   - Run focused tests while developing.
   - Run `just check` before delivery.
   - Run Claude Code review against the doc/code diff and repeat fix/review cycles until the review has no actionable
     findings.

## Test Plan

Body sections:

- Create with both `overview` and `detail`; read returns both.
- If Step 0 confirms `overview` is required, create without `overview` remains rejected.
- If Step 0 confirms `overview` is already optional, create without `overview` remains accepted and docs preserve that
  behavior.
- Create with `overview: []` is accepted whenever `overview` is supplied.
- Create without `detail`; read returns `detail: []`.
- Explicit empty `detail: []` renders the same user-visible content as an absent `detail` section.
- Patch only `detail`; `overview` is unchanged.
- Patch only `overview`; `detail` is unchanged.
- Patch both sections; both round-trip.
- Patch with `detail: []` replaces the detail section with an empty section; omitting `detail` preserves it.
- Patch with `overview: []` replaces the overview section with an empty section; omitting `overview` preserves it.
- Existing body with custom/unsupported top-level section keeps that section when `overview` or `detail` is patched.
- Validation errors under `detail` use paths like `detail.0.value.id`.
- Unsupported block types under `detail` use paths like `detail.0.type` with code `unsupported_block_type`.
- Stored unsupported blocks inside `overview` or `detail` are visible as unsupported placeholders on read, and sending a
  placeholder back with the same stored block type and original position preserves the matching stored block.
- If preflight confirms `overview` and `detail` share the cumulative block set, `detail` tests cover heading, paragraph,
  code, image, gallery, audio, and video. If block sets differ, replace this with per-section block coverage based on the
  verified definitions.
- Paragraph HTML that Wagtail normalizes or sanitizes round-trips in its saved normalized form; tests should include at
  least one input that changes under the sanitizer.

Video block:

- Existing choosable video ID converts to the internal block value.
- Missing video ID returns `detail.0.value.id` or `overview.0.value.id` with `not_found`.
- Real but not-choosable video ID is rejected like a missing video.
- Video block round-trips through create/read/patch.

Media listing:

- Anonymous users are rejected.
- Anonymous users receive the DRF unauthenticated response for the active authentication classes; authenticated users
  without Wagtail admin access receive `permission_denied`/HTTP 403.
- Users without Wagtail admin access are rejected.
- List endpoints include media the caller may choose.
- List endpoints exclude media outside the caller's choose permissions.
- List response items include `collection` with `id` and `name`, or `collection: null` only if preflight confirms legacy
  nullable collection rows exist.
- List endpoints apply `q` as a filter and return searched results in deterministic database ordering, not backend
  relevance ordering.
- List endpoints support repeatable `tag` filters with exact stored-name, no-API-case-normalization, AND semantics.
- List endpoints combine `q` and `tag` as intersection filters before deterministic ordering.
- Unsupported media list/discovery query parameters return `validation_error`/`unsupported_parameter`.
- Freshly uploaded media appears in unsearched lists and DB-filter `q` results immediately.
- After preflight verifies the field names, list endpoints use deterministic default ordering: image `-created_at, -id`,
  audio/video `-created, -id`. If preflight changes the field names, update this test expectation first.
- List endpoints respect the verified shared pagination parameter name, default size, and maximum page size; do not
  hard-code the current `pageSize`/40/200 expectation in tests until Step 0 confirms it.
- Under the stock policies, collection discovery returns the same usable collection IDs used by upload auto-selection for
  each media type.
- Collection discovery missing `type` returns `validation_error`/`required`; invalid `type` returns
  `validation_error`/`invalid_choice`.
- Collection discovery with no usable collections returns `200 OK` with an empty `results` list.
- Collection discovery is deterministically ordered by the verified collection ordering fields.

Media upload:

- Image upload creates a Wagtail image with `uploaded_by_user` set and returns an ID usable in `cover_image`.
- Image upload without `file` returns a `file` validation error.
- Oversized image upload returns a `file` validation error before save, using the verified Wagtail image upload limit.
- Audio upload accepts valid `mp3`, `m4a`, `oga`, or `opus` files using current validation.
- Audio upload without any audio file returns a `non_field_errors` validation error.
- Audio upload with more than one audio file field returns `non_field_errors` with code `too_many_files`.
- Oversized audio upload returns a validation error on the oversized submitted audio file field before duration probing.
- Video upload accepts a valid video file using current validation and returns the created video ID.
- Video upload without `original` returns an `original` validation error.
- Oversized video upload returns an `original` validation error before poster generation.
- Upload without `collection` succeeds when the caller has exactly one usable upload collection for that media type.
- Upload without `collection` returns a `collection` validation error with code `ambiguous` when the caller has multiple
  usable upload collections for that media type.
- Upload without `collection` returns `no_upload_collection` when the caller has no usable upload collection for that media
  type.
- Supplied missing or unusable `collection` IDs return HTTP 400 `validation_error` on `collection` with code
  `collection_permission_denied`, while malformed collection values return `invalid`.
- A well-formed nonexistent `collection` ID also returns `collection_permission_denied`, not a not-found or invalid-choice
  error.
- Video upload responses allow `poster: null` when no poster file was generated synchronously.
- Invalid image/audio/video uploads return `validation_error`.
- Audio upload/list responses include the stored `transcript_diarization_mode` field value.
- Editor audio upload rejects `transcript_diarization_mode=enabled` with the `validation_error` envelope and code
  `unsupported` at field path `transcript_diarization_mode`.
- Users missing image `add` or `choose` permission cannot upload images.
- Users missing audio/video `add` permission cannot upload audio/video.
- Audio/video upload returns `post_save_permission_denied`, deletes the object, and cleans up saved files if a
  patched/custom permission policy makes the saved owned object not choosable after owner assignment.
- Upload responses use the same edit/change permission semantics as list responses, but compute them with a direct
  per-object check on the created object. If preflight verifies that the stock owner policy grants `change` to fresh
  owned audio/video, fresh audio/video uploads should return a non-null `edit_url`; otherwise assert the verified
  nullable behavior. `edit_url: null` remains possible for image uploads, custom policies, or any object the caller can
  add/choose but not edit/change.
- Fresh upload response items include non-null `collection` with `id` and `name`.
- Uploaded media can be inserted into a post draft in the same test flow.

Regression:

- Existing `overview`-only clients keep working.
- `POST` and `PATCH` with `publish: true` return `validation_error` on `publish` with code `unsupported` and do not
  publish the page; if update did not already enforce this, this slice adds the guard.
- Existing stale `base_revision_id` conflict behavior is unchanged.
- Existing cover image clear behavior is unchanged.
- Existing docs examples remain accurate.
