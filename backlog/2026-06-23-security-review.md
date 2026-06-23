# Security Review Follow-ups

Date: 2026-06-23

Status: Open issue tracker for findings from a read-only deep security review. Findings came from a local Codex
review, four focused subagent reviews, npm audit, and Claude Code read-only cross-checks. This file should stay open
until every tracked issue is fixed, explicitly accepted, or moved to a more specific backlog item.

## Review Scope

- Public Django/Wagtail pages, feeds, APIs, comments, filters, galleries, and transcript/player endpoints.
- Admin/editor surfaces for audio, video, transcripts, Voxhelm, and the programmatic editing API.
- Media file handling, storage, transcript sidecars, management commands, and Voxhelm artifact downloads.
- Frontend templates and TypeScript where user/editor-controlled data reaches the DOM.
- JavaScript dependency audit for the Vite workspace.

## Severity Guide

- High: plausible content disclosure, authorization bypass, SSRF, or stored XSS on normal production paths.
- Medium: exploitable with authenticated/editor access, deployment misconfiguration, or narrower feature use.
- Low: development-only, operational hardening, supply-chain, or data-loss issues that should still be tracked.

## Tracking Summary

| ID | Severity | Area | Status |
| --- | --- | --- | --- |
| SEC-2026-001 | High | Restricted content | Fixed |
| SEC-2026-002 | High | Wagtail media admin | Open |
| SEC-2026-003 | High | Voxhelm artifact downloads | Open |
| SEC-2026-004 | High | Twitter card player | Fixed |
| SEC-2026-005 | Medium | Player transcript cache headers | Fixed |
| SEC-2026-006 | Medium | Closed comments | Fixed |
| SEC-2026-007 | Medium | Faceted navigation XSS | Fixed |
| SEC-2026-008 | Medium | Gallery image enumeration | Fixed |
| SEC-2026-009 | Medium | Voxhelm draft audio authorization | Open |
| SEC-2026-010 | Medium | Editor API admin gate | Open |
| SEC-2026-017 | Medium | Raw transcript artifact storage | Open |
| SEC-2026-011 | Medium | Private voice-reference storage | Open |
| SEC-2026-012 | Medium | Audio/video upload validation | Open |
| SEC-2026-013 | Medium | Media stale deletion scope | Open |
| SEC-2026-014 | Low | Media replacement durability | Open |
| SEC-2026-015 | Low | JavaScript dependency audit | Open |
| SEC-2026-016 | Low | Podlove remote script fallback | Open |

## High Priority

### SEC-2026-001: Restricted child pages leak through public lists, feeds, and facets

Status: Fixed

References:

- `src/cast/models/index_pages.py:186` and `src/cast/models/index_pages.py:195`
- `src/cast/models/repository/contexts.py:527`
- `src/cast/feeds.py:78`
- `src/cast/feeds.py:84`
- `src/cast/urls.py:37`
- `src/cast/api/views.py:227`

Exploit scenario:

A live `Post` or `Episode` protected with a Wagtail `PageViewRestriction` can still be selected by
`Post.objects.live().descendant_of(...)` and `Episode.objects.live().descendant_of(...)`. Public blog lists, feed
views, and facet-count APIs do not consistently apply request-aware page-view restriction checks. A visitor can learn
restricted titles, slugs, metadata, excerpts, and, for podcasts, potentially audio enclosure URLs. Public feed caching
can preserve the leaked response.

Fix direction:

- Add a request-aware public queryset/filter helper for index children that checks Wagtail page-view restrictions.
- Use it for blog/podcast lists, repository contexts, feeds, and facet APIs.
- Keep feed caching only for unrestricted public output, or vary/private-cache when request-specific access matters.
- Add regression tests with a live restricted post and a live restricted episode.

Done when:

- Anonymous users cannot see restricted child content in lists, feeds, or facet APIs.
- Authorized users still see content they are allowed to view where that is intended.
- Feed cache tests prove restricted output is not cached as a shared public response.

### SEC-2026-002: Custom Wagtail media and transcript admin views miss object-level permissions

Status: Open

References:

- `src/cast/wagtail_hooks.py:36`
- `src/cast/views/audio.py:24`, `src/cast/views/audio.py:114`, `src/cast/views/audio.py:174`
- `src/cast/views/video.py:23`, `src/cast/views/video.py:104`, `src/cast/views/video.py:164`
- `src/cast/views/transcript.py:143`, `src/cast/views/transcript.py:458`, `src/cast/views/transcript.py:605`

Exploit scenario:

The custom Wagtail admin views are registered behind `require_admin_access`, which checks access to the Wagtail admin
but does not enforce per-model, per-collection, or per-object permissions. A staff user with unrelated admin access can
potentially enumerate, choose, edit, or delete `Audio`, `Video`, and `Transcript` objects outside their collection or
ownership scope.

Fix direction:

- Use Wagtail collection permission policies for audio, video, and transcript models.
- Filter index and chooser querysets to objects the user can choose or change.
- Require explicit add, change, delete, and choose permissions at each view boundary.
- Return 403 or 404 consistently for unauthorized direct object URLs.

Done when:

- Limited Wagtail users cannot list, choose, edit, or delete media/transcripts outside their allowed collections.
- Superusers and properly authorized editors retain the expected workflows.
- Tests cover index, chooser, add, edit, and delete views for a restricted user.

### SEC-2026-003: Voxhelm artifact URLs allow SSRF and unbounded downloads

Status: Open

References:

- `src/cast/voxhelm.py:451`
- `src/cast/voxhelm.py:463`
- `src/cast/voxhelm.py:617`

Exploit scenario:

`build_url()` accepts absolute `http` and `https` artifact URLs, and `request_bytes()` downloads them with
`urlopen(...).read()` without a byte cap. A compromised or malicious Voxhelm endpoint could return an artifact URL
pointing at internal services, cloud metadata addresses, or a very large response. The worker would fetch and store the
response from the django-cast server environment.

Fix direction:

- Prefer relative artifact paths, or require artifact URLs to remain same-origin with the configured Voxhelm root.
- Reject loopback, link-local, private network, and non-HTTPS destinations after redirects.
- Stream downloads with a maximum byte count.
- Validate expected transcript content types and formats before staging.

Done when:

- Absolute artifact URLs cannot reach private/internal network targets.
- Oversized artifact responses fail before consuming unbounded memory or storage.
- Tests cover absolute URL rejection, redirect rejection, and size-limit behavior.

### SEC-2026-004: Twitter card player can expose draft or restricted episodes

Status: Fixed

References:

- `src/cast/views/meta.py:16`
- `src/cast/templates/cast/twitter/card_player.html:21`

Exploit scenario:

The Twitter card player view resolves the blog as live but fetches the episode from `Episode.objects.descendant_of(blog)`
without requiring `live=True` or applying request-aware page-view restriction checks. If an attacker guesses or learns a
draft or restricted episode slug, the card page can emit Podlove configuration, episode UUID, duration, and audio URL.

Fix direction:

- Require the target episode to be live and visible to the current request.
- Reuse the same public page-view restriction helper planned for SEC-2026-001.
- Ensure player configuration is serialized with a JSON-safe mechanism.

Done when:

- Draft and restricted episodes return 404 or 403 for anonymous card-player requests.
- Public live episodes keep rendering the card player.
- Tests cover draft, restricted, and public episodes.

## Medium Priority

### SEC-2026-005: Player transcript endpoint can cache editor-only responses as public

Status: Fixed

References:

- `src/cast/api/views.py:162`
- `src/cast/api/views.py:173`
- `src/cast/api/views.py:196`
- `src/cast/audio_access.py:53`

Exploit scenario:

`AudioPlayerTranscriptView` can authorize access through editable draft or restricted pages, but it always returns
`Cache-Control: public, max-age=3600, stale-while-revalidate=86400`. If an editor previews a draft or restricted
transcript through a shared proxy or CDN, the response can be stored as public and later served to anonymous users.

Fix direction:

- Use public cache headers only when the granting page is publicly viewable by anonymous users.
- Use `private, no-store` or equivalent for editor/draft/restricted access.
- Add `Vary: Cookie, Authorization` where authenticated access can affect the response.

Done when:

- Public transcript responses remain cacheable.
- Editor-only or restricted transcript responses cannot be stored as shared public cache entries.
- Tests assert cache headers for public, draft/editor, and restricted paths.

### SEC-2026-006: Closed comments can still be posted through the API path

Status: Fixed

References:

- `src/cast/models/pages.py:226`
- `src/cast/models/pages.py:371`
- `src/cast/comments/views.py:49`
- `src/cast/comments/views.py:272`
- `src/cast/comments/templates/comments/form.html:3`

Exploit scenario:

The template hides the form when comments are closed, but the AJAX comment post view resolves the target and saves
without enforcing `comments_are_open(target)`. Page API responses also expose `comments_security_data` unconditionally.
An attacker can fetch the target security data and post to the comment endpoint even after comments are closed.

Fix direction:

- Enforce `comments_are_open(target)` server-side after the submitted target object is resolved.
- Apply the same check to the stock post wrapper.
- Suppress `comments_security_data` from page API output when comments are closed.

Done when:

- Closed-comment targets reject new top-level comments and replies at the view layer.
- Open comments and existing author edit/delete behavior still work.
- Tests cover AJAX, stock post wrapper, and API serialization.

### SEC-2026-007: Stored XSS in public facet labels

Status: Fixed

References:

- `src/cast/filters.py:49`
- `src/cast/filters.py:93`
- `src/cast/filters.py:244`
- `src/cast/templates/cast/bootstrap4/blog_list_of_posts.html:45`

Exploit scenario:

The custom facet widget builds HTML strings with `mark_safe` and interpolates labels and attributes directly. Tag and
category names can become facet labels. A malicious editor or import path could create a tag/category containing HTML or
JavaScript and execute it for visitors on list pages that render the facet form.

Fix direction:

- Replace manual string concatenation with `format_html`, `format_html_join`, and escaped attribute handling.
- Avoid `mark_safe` for values derived from taxonomy labels, query strings, or request data.
- Add regression tests using malicious tag and category names.

Done when:

- Malicious facet labels are rendered as text, not executable HTML.
- Query-string preservation still works.
- Tests cover both tag and category filter rendering.

### SEC-2026-008: Gallery modal can enumerate arbitrary Wagtail image IDs

Status: Fixed

References:

- `src/cast/views/gallery.py:78`
- `src/cast/views/gallery.py:104`
- `src/cast/templates/cast/plain/gallery_modal.html:16`

Exploit scenario:

The public gallery modal accepts client-provided `image_pks` and fetches matching `Image` objects directly. A visitor
can request known or guessed image IDs and receive rendition URLs and alt text for images that may only be referenced by
draft or restricted content.

Fix direction:

- Bind modal requests to the gallery rendered on the public page.
- Sign the allowed image ID list when rendering the gallery, or validate image IDs against a public page/block context.
- Reject image IDs that were not part of the authorized gallery.

Done when:

- Arbitrary image IDs cannot be used to obtain gallery modal HTML.
- Existing public galleries still load adjacent images correctly.
- Tests cover valid signed galleries and rejected arbitrary IDs.

### SEC-2026-009: Voxhelm transcript generation authorizes live audio but enqueues draft audio

Status: Open

References:

- `src/cast/views/voxhelm.py:31`
- `src/cast/views/voxhelm.py:90`

Exploit scenario:

The episode transcript-generation view checks authorization against `episode.podcast_audio`, then loads the latest draft
revision and enqueues `draft_episode.podcast_audio`. If the draft points to different audio, the authorization decision
was made for one object while the submitted work uses another.

Fix direction:

- Load the exact revision/audio that will be enqueued before the authorization check.
- Authorize the user against that same audio object.
- Treat missing or changed draft audio as a fresh permission decision.

Done when:

- Users cannot enqueue Voxhelm work for draft audio unless they can change that exact audio.
- Tests cover live-audio authorization, draft-audio mismatch, and allowed draft-audio use.

### SEC-2026-010: Editor API lacks an explicit Wagtail admin-access gate

Status: Open

References:

- `src/cast/api/urls.py:13`
- `src/cast/api/editor/views.py:34`
- `src/cast/api/editor/views.py:159`
- `src/cast/api/editor/views.py:213`

Exploit scenario:

The editor API uses DRF `IsAuthenticated` plus Wagtail page permissions. If a site has authenticated non-admin users
with page permissions but without `wagtailadmin.access_admin`, those users may be able to create or update drafts
through the programmatic API even though they cannot access Wagtail admin.

Fix direction:

- Decide whether the API is explicitly admin-only or whether non-admin page-permission users are supported by design.
- If admin-only, add a DRF permission requiring `wagtailadmin.access_admin` or equivalent staff/admin gate.
- Keep the existing page-level add/change checks.

Done when:

- The intended actor model is documented.
- Tests prove non-admin authenticated users are allowed or denied according to that model.

### SEC-2026-017: Raw transcript artifacts can bypass authorization and sanitization on public media storage

Status: Open

References:

- `src/cast/models/transcript.py:174`
- `src/cast/models/transcript.py:195`
- `src/cast/views/transcript.py:737`
- `src/cast/views/transcript.py:779`

Exploit scenario:

Transcript endpoint views authorize access through `authorize_transcript_access` and sanitize public speaker labels
before returning transcript JSON, VTT, HTML, or DOTe payloads. The underlying `podlove`, `vtt`, and `dote` files are
stored with the default media storage while only the `speakers` sidecar explicitly uses private voice-reference storage.
If default media is public, a leaked or predictable raw transcript file URL can bypass both page-access checks and
speaker-label sanitization. This is especially relevant for episodes that were public and later restricted, CDN/proxy
logs, manually uploaded transcript filenames, or any deployment where media URLs are exposed outside the authorizing
views.

Fix direction:

- Store raw transcript artifacts on private storage and serve them only through authorizing/sanitizing views.
- If direct storage access remains supported, document that transcript files must not be publicly served.
- Consider a migration/management command to move existing transcript artifacts to private storage.
- Preserve public endpoint URLs so external consumers keep using the controlled views.

Done when:

- Anonymous users cannot fetch raw transcript artifacts for restricted or draft episodes through direct media URLs.
- Public transcript endpoints still serve sanitized transcript formats for authorized public content.
- Tests cover restricted transcript direct-file behavior and sanitized endpoint behavior.

### SEC-2026-011: Private voice-reference and speaker sidecar files can fall back to public default storage

Status: Open

References:

- `src/cast/models/contributors.py:98`
- `src/cast/models/contributors.py:162`
- `src/cast/models/transcript.py:195`
- `docs/media/audio-and-transcripts.rst:323`

Exploit scenario:

If `STORAGES["cast_voice_references"]` is missing, voice reference clips and transcript speaker sidecar files fall back
to `default_storage`. On deployments where default media storage is public, private editorial voice samples and speaker
metadata can become web-accessible if the object key is known or leaked.

Fix direction:

- Fail closed for these private files, or add a system check that errors in non-development deployments without a
  private storage alias.
- Ensure any Voxhelm handoff uses short-lived signed access rather than public URLs.
- Update docs to make the storage requirement explicit.

Done when:

- Production-like settings cannot silently store private voice files in public media storage.
- Tests cover missing storage alias behavior.
- Documentation reflects the required storage configuration.

### SEC-2026-012: Audio/video uploads lack server-side media validation before ffmpeg/ffprobe

Status: Open

References:

- `src/cast/forms.py:50`
- `src/cast/forms.py:158`
- `src/cast/models/audio.py:67`
- `src/cast/models/audio.py:146`
- `src/cast/models/video.py:66`
- `src/cast/models/video.py:97`
- `src/cast/api/views.py:73`

Exploit scenario:

Authenticated uploaders can submit arbitrary files into audio/video fields with limited server-side validation before
ffmpeg/ffprobe processing. Malformed or oversized files increase parser and resource-exhaustion risk, and unsafe active
content could be stored under public media if a storage backend serves it directly.

Fix direction:

- Add extension, content-type, and magic/container validation appropriate to supported audio/video formats.
- Enforce upload size limits before expensive processing.
- Run ffmpeg/ffprobe with resource limits and failure isolation.
- Serve media from a cookieless/no-sniff domain where possible.

Done when:

- Unsupported formats and oversized files are rejected before ffmpeg/ffprobe work.
- Valid supported media still uploads and extracts metadata.
- Tests cover invalid extension, invalid magic bytes, and oversized upload paths.

### SEC-2026-013: `media_stale --delete` can delete managed private files or unrelated storage keys

Status: Open

References:

- `src/cast/management/commands/media_stale.py:44`
- `src/cast/models/transcript.py:225`
- `src/cast/models/contributors.py:162`
- `src/cast/management/commands/media_stale.py:73`
- `src/cast/utils.py:7`

Exploit scenario:

The stale-media command uses a manual list of model path helpers and then walks the whole storage tree. Private speaker
sidecar files and contributor voice references are not clearly included in the modeled path set, and unrelated keys in
the same storage/prefix can be deleted as stale when `--delete` is used.

Fix direction:

- Discover model `FileField` paths systematically or explicitly include every managed private file field.
- Restrict scanning and deletion to known django-cast-managed prefixes.
- Produce a dry-run manifest and require explicit confirmation for destructive deletion.

Done when:

- Known private file fields are retained by stale-media detection.
- Unrelated same-bucket/prefix keys are not considered deletable by default.
- Tests cover dry-run and delete behavior for modeled, unmodeled, and unrelated files.

## Low Priority

### SEC-2026-014: `media_replace --yes` deletes the production object before replacement save succeeds

Status: Open

References:

- `src/cast/management/commands/media_replace.py:52`

Exploit scenario:

The replacement command can delete the old storage object before the new file has been safely saved and verified. A
storage or network failure during replacement can cause avoidable media loss.

Fix direction:

- Upload the replacement to a temporary key first.
- Verify the new object, then promote/copy it into place.
- Keep the old object until the replacement is known to be durable.

Done when:

- Simulated storage failures do not delete the original media object.
- Successful replacement keeps current behavior for callers.

### SEC-2026-015: JavaScript dependency audit reports vulnerable esbuild dev server

Status: Open

References:

- `javascript/package-lock.json:1345`
- `npm audit --json`
- Advisory: `https://github.com/advisories/GHSA-g7r4-m6w7-qqqr`

Exploit scenario:

The JavaScript workspace currently installs an esbuild version in the advisory range for arbitrary file reads through
the development server on Windows. This is a development-surface vulnerability, but the dependency should still be
updated in the normal maintenance flow.

Fix direction:

- Update Vite/esbuild through `npm audit fix` or a controlled dependency bump.
- Keep development servers bound to localhost.
- Run the JavaScript test/build commands after the bump.

Done when:

- `npm audit` no longer reports this advisory.
- JavaScript build and tests pass.

### SEC-2026-016: Podlove component falls back to a mutable remote script URL

Status: Open

References:

- `javascript/src/audio/podlove-player.ts:103`
- `javascript/src/audio/podlove-player.ts:440`
- `src/cast/templates/cast/audio/audio.html:17`

Exploit scenario:

The default template passes a local static Podlove embed script, which is safe for first-party control. The web
component itself falls back to `https://cdn.podlove.org/web-player/5.x/embed.js` when no `data-embed` is provided. A
consumer theme that omits `data-embed` would execute a mutable third-party script for visitors.

Fix direction:

- Fail closed when `data-embed` is missing, or default to a versioned local static asset.
- Document the theme requirement if themes are expected to provide the script URL.
- Add a frontend test for missing `data-embed`.

Done when:

- Omitting `data-embed` does not silently load third-party JavaScript.
- Existing first-party static configuration continues to work.

## Reviewed And Not Currently Tracked As Findings

- Public transcript JSON, VTT, HTML, and DOTe views use the central audio/transcript authorization helper before
  serving transcript files. Raw transcript artifact storage is tracked separately in SEC-2026-017 because direct media
  URLs can bypass those views.
- Comment self-editing and deletion use POST/CSRF, session ownership, row locks, actionable-comment checks, moderation
  revalidation, and signed-cookie-session protection. The remaining comment issue is the closed-comment creation bypass
  tracked in SEC-2026-006.
- The editor API validates structured body block types and image references through server-side serializers. The
  separate issue is the actor/admin-access boundary tracked in SEC-2026-010.
- Development and styleguide routes are disabled by default behind `CAST_ENABLE_DEV_TOOLS`. Remote media styleguide
  fetching remains a deployment-controlled development risk, not a normal production path.
- Voxhelm request authorization is only sent to the configured root origin, which mitigates token leakage during
  artifact SSRF. The artifact destination and size issues remain tracked in SEC-2026-003.
- The gallery JavaScript uses fixed markup for modal controls; the security issue is the server-side arbitrary image
  ID trust boundary tracked in SEC-2026-008.

## Closure Checklist

- [ ] High-priority findings fixed or explicitly accepted with documented rationale.
- [ ] Medium-priority findings fixed, split into implementation tasks, or explicitly deferred.
- [ ] Low-priority findings triaged into maintenance work.
- [ ] Regression tests added for every fixed behavior change.
- [ ] Documentation and release notes updated for behavior, settings, or workflow changes.
- [ ] `just check` passes for implementation changes.
