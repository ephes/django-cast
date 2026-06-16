# Authorize public audio & transcript object endpoints

Date: 2026-06-15
Status: Approved (access model confirmed with maintainer)

## Problem

Several public endpoints serve `Audio` / `Transcript` content addressed by raw object
ID. They use `get_object_or_404(Transcript, pk=...)` / `Audio.objects.all()` and treat
the `episode_id` / `post_id` query parameter only as a hint for *speaker-label
sanitization* — never as an access gate. As a result:

- A bare object ID returns content even when no live, public episode/post references it.
- A *mismatched* `episode_id` (an ID that does not reference the requested object) is
  silently ignored rather than rejected.
- Wagtail page view restrictions (login / password / group) on the owning page are not
  respected.

Affected routes:

- `cast:podlove-transcript-json` — `/transcripts/podlove/<pk>/`
- `cast:podcastindex-transcript-json` — `/transcripts/podcastindex/<pk>/`
- `cast:webvtt-transcript` — `/transcripts/vtt/<pk>/`
- `cast:html-transcript` / `cast:html-transcript-no-post` — `/transcripts/html/<pk>/[<post_pk>/]`
- `cast:api:audio_podlove_detail` — `/api/audios/podlove/<pk>/[post/<post_id>/]`
- `cast:api:audio_player_transcript` — `/api/audios/<pk>/player-transcript/` (already
  strict on `live=True`; extended here only with the editor fallback)

The user-facing `cast:episode-transcript` view already resolves the episode by slug under
its blog with `live=True` and reads the transcript from the episode, so it is already
anchored and is **out of scope** except as a reference pattern.

## Access model (approved)

Serve the object only when **either** path holds:

1. **Public path** — the object is anchored to an episode/post that is `live=True`
   **and** whose Wagtail view restrictions the current request satisfies.
2. **Editor path** — the requesting user has `can_edit` permission on a referencing
   page (covers Wagtail preview and never-published drafts).

Otherwise raise `Http404`.

Anchor resolution is **hybrid**:

- **Explicit anchor given** (`episode_id` or `post_id`/`post_pk`): resolve it; it must
  reference the requested object; it must satisfy the public path or the editor path.
  Any failure — unresolved, mismatched, not live & not viewable & not editable — is a
  **404**. There is no silent fallback to "some other episode".
- **No explicit anchor**: search the episodes/posts referencing the object; allow if any
  one of them satisfies the public path or the editor path. Prefer returning a live
  anchor (for the downstream speaker sanitization). None qualifying → **404**.

All denials return `Http404` (never `403`) so object existence is not leaked. Existing
"file missing" branches keep their current 404 responses.

## Components

### `page_is_publicly_viewable(page, request) -> bool`

Returns `True` when `page` is `live` and every restriction from
`page.get_view_restrictions()` returns `True` from `restriction.accept_request(request)`.
A page with no restrictions and `live=True` is publicly viewable. New helper.

### `user_can_edit_page(page, user) -> bool`

Thin wrapper over the existing idiom `page.permissions_for_user(user).can_edit()`
(already used in `views/voxhelm.py`), guarded for anonymous users.

### `authorize_audio_access(request, *, audio, explicit_anchor_id=None) -> Page`

The single decision function, living in a new `cast/audio_access.py` module (kept separate
from `transcript_sanitization.py` so access control and speaker-label sanitization stay
decoupled). Returns the resolved granting page when access is granted, or raises `Http404`.
When access is granted via the no-anchor public path it returns a live referencing episode.
A thin `authorize_transcript_access(request, *, transcript, ...)` wraps it using
`transcript.audio`.

Referencing relationships:
- Episodes reference audio via `Episode.podcast_audio`.
- Posts/Episodes reference audio via `media_lookup["audio"]`.
- Transcripts reference audio via `Transcript.audio`; callers pass `transcript.audio`.

## Endpoint changes

Each endpoint calls the authorization helper **before** opening any file:

- `views/transcript.py`: `podlove_transcript_json`, `podcastindex_transcript_json`,
  `webvtt_transcript`, `html_transcript`, plus a `request_may_view_page` gate on the
  canonical `episode_transcript` view. These keep calling `public_episode_from_request`
  for the speaker-sanitization episode context (now safe — see below).
- `api/views.py`: `AudioPodloveDetailView.retrieve` authorizes **every** supplied anchor
  (`post_id` route kwarg and/or `episode_id` query param); `AudioPlayerTranscriptView`
  gains the editor fallback (so preview of an unpublished draft works for an authorized
  editor).

## Speaker-label aggregate fix

Authorization alone is not sufficient: when no concrete episode is in the sanitization
context (a no-anchor transcript hit, or the podlove serializer's `?episode_id=` path,
which keys sanitization off the `post` context rather than `episode_id`), the speaker-label
and speaker-mapping helpers fall back to aggregating over **all** live episodes that share
the audio. That aggregate previously included view-restricted episodes, leaking their
contributor/speaker labels into anonymous output. The aggregate now excludes any episode
that carries a Wagtail view restriction (`_episode_is_publicly_visible` in
`transcript_sanitization.py`) — restriction *existence* is request-independent, so a
restricted episode is never public. The explicit per-episode path is unchanged and is only
reached with an already-authorized episode.

## Error handling

- Denied access → `Http404`.
- Missing/absent transcript file → existing 404 responses unchanged.
- Every supplied anchor must authorize (fail-closed): a malformed, non-existent, mismatched,
  or non-public `episode_id`/`post_id` is a hard `404`, even when another valid anchor is
  also present. Absent anchors fall through to the no-anchor search (404 if nothing
  qualifies).

## Testing

Focused regression matrix (anonymous unless noted):

- Live public episode referencing the object → 200.
- Feed-style URL with valid `?episode_id=` → 200.
- Draft / never-published episode → 404 (anonymous); 200 for an editor with `can_edit`
  (preview path) and for the `player-transcript` endpoint too.
- Object not referenced by any episode/post (unattached) → 404.
- Mismatched `episode_id` (valid episode, but does not reference the object) → 404.
- View-restricted (login / password / group) live episode → 404 for an anonymous /
  unauthorized request; 200 for a logged-in user who satisfies the restriction.
- Existing speaker-sanitization behavior preserved for the now-anchored requests.

## Docs

- Add a release note to `docs/releases/0.2.59.rst` describing the hardening.
- Mark the BACKLOG.md "Authorize public audio and transcript object endpoints" item done
  (move its user-facing summary into the release note per the backlog convention).

## Out of scope

- `cast:episode-transcript` (already anchored).
- The cast-vue SPA `podlove_players` API path and feed *generation* logic (feeds already
  emit `?episode_id=`).
- Rate limiting / broader API authentication changes.
