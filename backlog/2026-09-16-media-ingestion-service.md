# Media ingestion service

Date: 2026-09-16   Status: Implemented in commits ``f1162cf5``, ``7e98f13f``, ``db38dba8``, ``72ddd2dd``,
``52f9b9f3``, ``8c5928e3``, ``1cf0e857``, ``4f700564``, and this note's closing private-address-policy commit.

## Problem

Upload safety is a property of one transport, not of the media layer. The editor API is the only entry point that
serialises uploads per user and bounds ffprobe/ffmpeg time: `EditorAudioListCreateView.post` and
`EditorVideoListCreateView.post` wrap `_post_locked` in `_with_upload_lock` (`src/cast/api/editor/media.py:348-349`,
`:411-412`, implementation `:460-470`, key `cast:editor-media-upload:{user.pk}`), run `form.save()` inside
`media_probe_budget(_editor_media_probe_seconds())` (`:377-378`, `:425-426`), and the audio view maps probe
exceptions to the flat `probe_timeout`/`probe_failed`/`cleanup_failed` envelopes after `_cleanup_media_object`
(`:260-269`, `:379-391`); the video view has no probe `except` because `Video.create_poster` swallows every exception
(`models/video.py:155-164`); `LegacyVideoCreateView` (`:439-457`) inherits lock and budget. The Wagtail admin has none
of it: `MediaAdminViews.add`, `edit` and `chooser_upload` call `form.save()` directly (`src/cast/views/media.py:124`,
`:157`, `:301`), as does `_handle_transcript_form_save` (`src/cast/views/transcript.py:423`). Those reach
`save_*_with_derivations` (`src/cast/media_derivation.py:84-149`), whose probes are bounded only by the per-call
default of 30 s (`src/cast/media_probe.py:38-40`; `models/audio.py:181`, `models/video.py:109,143`), so an admin audio
upload can run three 30 s probes back to back with no lock: open security observation 2 in
`backlog/2026-09-07-security-review.md`.

The admin edit path is unsafe in the other direction. `MediaAdminViews.edit` calls `config.delete_old_files(obj_id,
form)` before `form.save()` (`views/media.py:156-157`); `_delete_old_audio_files`/`delete_old_audio_files`
(`views/audio.py:19-26`, `:47-51`) and `_delete_old_video_files` (`views/video.py:37-40`) delete the replaced file
immediately. Since 89132ea3 `AudioForm.save` clears `duration` on a changed file field (`src/cast/forms.py:274-284`),
so `create_duration` runs on every admin replacement; when ffprobe then fails, `save_audio_with_derivations` rolls
the row back to a file name that no longer exists and the new upload is orphaned (review finding V1). Both production
consumers make this worse: `../homepage` and `../python-podcast` run `S3Boto3Storage` with `AWS_S3_FILE_OVERWRITE =
True` (`config/settings/base.py:342`, `:310`) and `Audio`/`Video` use flat `upload_to` directories
(`models/audio.py:81-84`, `models/video.py:68`), so a same-named replacement overwrites the old object in place during
`FieldFile.pre_save`, before any guard could act. `StagedFileReplacementGroup` (`src/cast/file_replacement.py:28-75`)
already stages content under `fresh_file_name` (uuid suffix, `:112-126`), saves atomically and deletes old files in
`on_commit`, but takes `bytes` and serves only `transcripts/services.py`, `voxhelm/service.py`, `models/transcript.py`.

Two smaller gaps sit in the same seam. `TranscriptForm._load_json` runs `json.load` over the whole upload
(`forms.py:363-366`) while `clean_vtt` reads a 32-byte header (`:346-349`, `:376`); nothing caps transcript bytes
although Voxhelm artifacts are capped at 10 MiB (`MAX_VOXHELM_ARTIFACT_BYTES`, `src/cast/voxhelm/client.py:18`): open
security observation 1. And the only SSRF-aware HTTP code is inside the Voxhelm client (`:47-83`, `:150-187`). Remote
media import, feed import and embeds are all deferred on these two abstractions (`BACKLOG.md:28-31,117-126,178-186`).

## Current call sites

| Site (file:line) | Owns today | On paths that bypass it |
| --- | --- | --- |
| Editor audio / video POST (`api/editor/media.py:348-391,411-431`) | lock, budget, codes, cleanup | reference |
| Admin add / chooser upload (`views/media.py:120-125,290-302`) | permission check, `form.save()` | 30 s per probe |
| Admin edit (`views/media.py:153-158`) | `delete_old_files` then `form.save()` | old file gone if save fails |
| Transcript add / chooser (`views/transcript.py:538-557`) | `_views.add`/`_views.chooser_upload` | shared views |
| Transcript edit (`views/transcript.py:415-423`) | `TranscriptForm` bind, `form.save()` | old artifact orphaned |
| `_delete_old_*_files` (`views/audio.py:19-26,47-51`, `views/video.py:37-40`) | eager delete | not transactional |
| `AudioForm.save` (`forms.py:274-284`) | clears duration, derivations, chaptermarks | m2m outside atomic |
| `save_*_with_derivations` (`media_derivation.py:84-149`) | atomic row, probes via `run_media_probe` | no budget |
| `TranscriptForm.clean_*` (`forms.py:312-349,363-382`) | JSON shape, WEBVTT header | unbounded `json.load` |
| Voxhelm fetch helpers (`voxhelm/client.py:47-83,150-187,256-262`) | no redirects, same origin, caps | Voxhelm-only |

## Target design

One module, `src/cast/media_ingest.py`, owns the ingest contract. It is a media-layer service: it imports
`media_probe`, `media_derivation`, `file_replacement` and `appsettings`, never DRF or Wagtail admin. Callers hold the
per-user lock at their own scope, hand over a bound and validated form plus a policy, and translate typed exceptions.

```
transport: with upload_lock(user):        <- transport-owned; wraps collection resolution and form binding
               form (bound, valid) + IngestPolicy  ->  media_ingest.ingest_upload(form, *, policy) -> Model
ingest_upload (never touches the cache):
    1. rename ......... every uncommitted tracked FieldFile gets fresh_file_name(name): pre_save writes a new key
    2. probe budget ... media_probe_budget(policy.probe_seconds) unless None
    3. atomic ......... using = normalize_model_save_arguments(form.instance, (), {})[1]; transaction.atomic(using):
                        guard = FileFieldReplacementGuard.track(instance, fields); obj = form.save()
                        guard.commit()   -> on_commit(using): delete old names that changed
       on error ....... guard.rollback() -> delete names written during this save, restore old names; on the create
                        path delete the row if it survived; raise MediaProbeTimeout/MediaProbeFailed/
                        MediaIngestCleanupFailed (original exception chained)
```

Public surface (all in `cast/media_ingest.py`; validation stays in `form.clean_*` via `media_validation`):

```python
@dataclass(frozen=True)
class IngestPolicy:
    probe_seconds: float | None      # None: no cumulative budget (transcripts)
    file_fields: tuple[str, ...]     # guard tracks and renames these: AUDIO_FILE_FIELDS, ("original", "poster")
def editor_policy(file_fields) -> IngestPolicy     # CAST_EDITOR_MEDIA_PROBE_SECONDS, read per call
def admin_policy(file_fields) -> IngestPolicy      # CAST_MEDIA_PROBE_SECONDS (new, default 30), read per call
TRANSCRIPT_POLICY = IngestPolicy(probe_seconds=None, file_fields=("podlove", "dote", "vtt"))
class MediaIngestError(Exception): ...   # subclasses MediaUploadInProgress (upload_lock only), MediaProbeTimeout
                                         # (TimeoutExpired/AudioDurationProbeTimeout), MediaProbeFailed
                                         # (AudioDurationProbeError), MediaIngestCleanupFailed (rollback raised)
def upload_lock(user, *, seconds=None) -> ContextManager[None]  # cache.add on the unchanged editor key; non-reentrant
def ingest_upload(form, *, policy: IngestPolicy) -> Any
def cleanup_new_media_object(obj, field_names) -> bool                   # today's _cleanup_media_object
```

The lock is deliberately not part of `IngestPolicy` or `ingest_upload`: `cache.add` is non-reentrant, and the editor
needs the lock around `_resolve_collection` (`api/editor/media.py:352-354`) and form binding, before a form exists.
Each transport enters `upload_lock` once: the editor keeps `_with_upload_lock(user, callback)` as
`with upload_lock(user): return callback()` plus the 429 mapping around `_post_locked`; `MediaAdminViews` enters it
around bind, validate and `ingest_upload` when `config.lock_uploads` is true; importers wrap their whole unit of work.
`MediaAdminConfig` gains `ingest_policy: Callable[[], IngestPolicy]` (zero-arg factory, so settings are read
per request) and `lock_uploads: bool = False`; audio and video set `lambda: admin_policy(AUDIO_FILE_FIELDS)` /
`lambda: admin_policy(("original", "poster"))` with `lock_uploads=True`, transcripts `lambda: TRANSCRIPT_POLICY`.

`FileFieldReplacementGuard` joins `StagedFileReplacementGroup` in `cast/file_replacement.py` and shares
`_set_field_name` (which `models/transcript.py` also uses). It must read the stored names from the database, not from
the instance: `BaseModelForm._post_clean` already ran `construct_instance` during `is_valid()`, so by the time
`ingest_upload` sees a bound, valid form the tracked `FieldFile`s hold the new upload (renamed by step 1), never the
stored one. `track(instance, fields)` therefore snapshots `(field, stored_name)` from
`type(instance)._default_manager.using(using).filter(pk=instance.pk).values_list(*fields)` - the reload
`_delete_old_audio_files` does today with `get_object_or_404` (`views/audio.py:47-51`) - and snapshots nothing when
`instance.pk` is `None`. On success it registers `on_commit(delete stored names that changed)`; on failure it deletes
the names written during the save and restores the stored ones. It never deletes a name equal to its snapshot, like
`StagedFileReplacementGroup.rollback` (`:69-71`); the rename step makes that rule sufficient, since `pre_save` always
writes `stem-<12 hex>.ext` and never reuses the old key even where `get_available_name` returns its input unchanged
(`AWS_S3_FILE_OVERWRITE = True`), and a same-named create cannot clobber another row's key. Deletion strictness
differs by direction: post-commit deletion of a replaced file stays best-effort through `_delete_file`, which
suppresses every storage error (`file_replacement.py:170-172`), because the new row is already committed and the
caller has nothing to fix; rollback deletion uses a strict helper that lets the storage error surface, so
`ingest_upload` can raise `MediaIngestCleanupFailed`; built on `_delete_file` that exception would be unreachable
and uncoverable. The guard never reads content into memory (a 2 GiB video stays a streaming write); `poster` is
tracked so a failed video save removes it.
Wrapping the whole `AudioForm.save` means `_save_m2m()` and `save_chaptermarks()` (chapter ffprobe included) now
commit atomically with the row; today only `save_audio_with_derivations` is atomic (`media_derivation.py:92-99`).
`Transcript.speakers` (`models/transcript.py:66-67`) is excluded from `TRANSCRIPT_POLICY`: the form never uploads it;
only `transcripts/services.py` writes it, via its own staged group.

Error mapping per transport (editor codes, messages and statuses byte-identical to today):

| Exception | Editor API (`api/editor/media.py`) | Wagtail admin (`views/media.py`, `views/transcript.py`) |
| --- | --- | --- |
| `MediaUploadInProgress` | `rate_limited` 429, same detail text | non-field form error, existing `messages.error` |
| `MediaProbeTimeout` | `probe_timeout` 422 (cleanup already done) | non-field error "probing exceeded the budget" |
| `MediaProbeFailed` | `probe_failed` 422 | non-field error "Audio probing failed" |
| `MediaIngestCleanupFailed` | `cleanup_failed` 500 | re-raised (500; logged) |

Video probe failures never surface on any transport: the poster is optional (`docs/reference/api.rst:1121-1125`,
pinned by `test_video_upload_poster_probe_timeout_succeeds_without_poster`), so `ingest_upload` must not add a video
failure mode and the translation stays generic (no `pragma: no cover`). `_cleanup_media_object` stays a module
attribute of the editor module (`= cleanup_new_media_object`) because the post-save permission check and its cleanup
remain in the view. `MediaAdminConfig.delete_old_files` and the three `*delete_old_*_files` helpers are deleted.

The fetch helper is a second, independent module `src/cast/safe_fetch.py` (`FetchError` and its subclass
`ResponseTooLarge` omitted below):

```python
@dataclass(frozen=True)
class FetchPolicy:
    allowed_origins: frozenset[tuple[str, str]] | None   # (scheme, netloc); None = any http(s)
    max_bytes: int
    timeout: float
    follow_redirects: bool = False
    block_private_addresses: bool = True                # loopback/link-local/RFC1918/ULA/multicast rejected
def open_url(request, *, timeout, follow_redirects=True) -> ReadableResponse   # moved verbatim, NoRedirectHandler too
def read_response_bytes(response, *, max_bytes=None) -> bytes                  # raises ResponseTooLarge
def read_http_error_detail(exc, *, max_bytes) -> str
def fetch_bytes(url: str, *, policy: FetchPolicy, headers=None, method="GET", data=None) -> bytes
```

`voxhelm/client.py` imports the moved helpers, keeps its `MAX_VOXHELM_*` constants, passes
`max_bytes=MAX_VOXHELM_ERROR_BYTES` at call time (a test patches that constant) and wraps `ResponseTooLarge` into
`VoxhelmError` with today's message; `cast.voxhelm.__init__` re-exports keep resolving and Voxhelm still allows
private origins (`block_private_addresses=False`, same-origin only).

Why a new module rather than `media_derivation`: the models and `file_replacement` import it lazily, and
`appsettings` plus transport-facing exceptions would widen every model save's import graph. Why not a form mixin:
importers have no form (they call `ingest_upload` with a thin `ModelForm`-shaped adapter), and the lock must cover
work done before any form is built.

## Compatibility

- Wagtail 7.0 LTS through 8.0: every API touched exists identically in `.tox/py312-django52-wagtail70` (Wagtail
  7.0.9 / Django 5.2.17) and `.tox/py312-django61-wagtail80` (Wagtail 8.0 / Django 6.1.1), checked by script:
  `BaseCollectionMemberForm.__init__` reading `permission_policy`, `CollectionOwnershipPermissionPolicy` with the
  four permission methods used by `views/media.py`, `render_modal_workflow`, `wagtail.admin.messages.error/button`,
  `transaction.on_commit`, `cache.add`. No Wagtail hook or private API is needed (`.venv` holds Wagtail 7.4.3, not
  8.0 as the brief said). Django's `*_UPLOAD_MAX_MEMORY_SIZE` settings do not cap file uploads.
- Settings: `CAST_EDITOR_MEDIA_PROBE_SECONDS` (10) and `CAST_EDITOR_MEDIA_UPLOAD_LOCK_SECONDS` (7200) keep their
  names and defaults; the lock TTL now also governs admin uploads. New registry entries: `CAST_MEDIA_PROBE_SECONDS`
  (default 30, no `check_type`, like the editor setting, which is read through `float(...)` and accepts `12.5`; 30
  equals today's single-probe timeout, so a one-probe upload is unchanged while multi-step probing is now bounded)
  and `CAST_TRANSCRIPT_UPLOAD_MAX_BYTES` (`check_type=int`, default 10485760, matching `MAX_VOXHELM_ARTIFACT_BYTES`).
  Both get `TYPE_CHECKING` stubs and `settings.rst` sections. `../homepage` and `../python-podcast` set none of the
  four names; both run `FileBasedCache`, which the lock tolerates (`add` is check-then-set).
- Storage: the rename makes the guarantee independent of `AWS_S3_FILE_OVERWRITE`; nothing relies on stable basenames.
- Theme repos `../cast-bootstrap5`, `../cast-vue`: no template, URL or block contract changes; no import of
  `cast.forms`, `cast.views.*` or `media_derivation`. `../python-podcast/tests/e2e` imports
  `save_audio_with_derivations`, whose signature does not change. `../daybook/src/daybook/cast_client.py` uploads only
  images (`upload_image`, `:512-528`); the codes it could meet (`rate_limited`, `probe_timeout`, `probe_failed`,
  `cleanup_failed`, `no_upload_collection`, `post_save_permission_denied`) and `docs/reference/api.rst` stay identical.
- Test contract: every HTTP-level editor assertion stays as is. Patch targets that move with the code:
  `cast.api.editor.media.media_probe_budget` (`tests/api/editor_media_test.py:405`) and the two probe-path cleanup
  patches `cast.api.editor.media._cleanup_media_object` (`:353`, `:427`) to `cast.media_ingest.*`. The two post-save
  permission patches (`:304`, `:541`) and the direct calls `_with_upload_lock` (`:453`) and `_cleanup_media_object`
  (`:592`, `:602`) keep working through the module-level adapters. Voxhelm: `cast.voxhelm.client.build_opener`
  (`tests/voxhelm/settings_client_test.py:642`) and `cast.voxhelm.client.urlopen` (`:700`, `:716`, `:731`, `:739`)
  move to `cast.safe_fetch`; `cast.voxhelm.client.MAX_VOXHELM_ERROR_BYTES` (`:708`) stays and requires the call-time
  `max_bytes=` argument above; `cast.voxhelm.client.open_url` patches keep working (`request_bytes` resolves the name
  in its module). `tests/audio_views_test.py:512-520` (unit test of `delete_old_audio_files`) is deleted with it;
  `tests/video_upload_test.py:97-108` pins the shared lock key for the legacy endpoint.
- Admin behavior that changes on purpose: a second concurrent admin audio/video upload by the same user is refused
  with a form error; replaced admin files are deleted after commit instead of before save; stored basenames carry a
  12-hex suffix; over-cap transcript uploads are rejected before parsing. Redirects, messages, chooser JSON unchanged.

## Security considerations

- Lock and budget become properties of every upload transport, closing the admin bypass without weakening the editor
  (10 s; admin 30 s cumulative). The lock stays a per-user fairness control needing a shared cache (docs unchanged).
- The guard plus rename removes the orphan-plus-dangling-name window on replacement (V1) and the orphaned new file on
  a failed create, on overwrite-capable storages too, and stops a same-named create from clobbering another object.
- Transcript caps bound memory before `json.load` via `read(max_bytes + 1)`, not the client-reported size; VTT too.
- `safe_fetch` disables redirects by default, enforces an origin allowlist, caps the response, and rejects private,
  loopback and link-local addresses at resolution time. Connect-time IP pinning (the `../django-chat` reference) is
  out of scope; a documented hook is left. Voxhelm keeps its permissive private-network policy (operator-configured).

## Implementation slices

1. Lock, exceptions, policies, setting. Create `cast/media_ingest.py` with `IngestPolicy`, the exception hierarchy,
   `upload_lock`, `editor_policy`/`admin_policy` and `cleanup_new_media_object`; register `CAST_MEDIA_PROBE_SECONDS`
   (registry entry, `TYPE_CHECKING` stub, `settings.rst` section, release-note line) so `admin_policy` can run;
   `_with_upload_lock` and `_cleanup_media_object` in the editor become module-level adapters. Tests:
   `tests/media_ingest_test.py` (owner token, TTL, nested lock refused, policies read settings). ~150 lines.
2. `ingest_upload` for creates. Rename step, budget, atomic wrapper, probe-exception translation, create-path
   cleanup; editor audio/video views call it and map exceptions to the unchanged flat errors; patch targets `:353`,
   `:405`, `:427` move. Tests: editor suite green with unchanged assertions; unit tests for translation and the
   uuid-suffixed basename. Docs: release note "editor upload path now shared with the admin". ~200 lines.
3. `FileFieldReplacementGuard` in `file_replacement.py`. Snapshot from the database, commit/rollback with
   `on_commit(using=...)` deletion, strict rollback deletion; wired into `ingest_upload` for
   `instance.pk is not None`. Tests: `tests/file_replacement_test.py` additions with
   `django_capture_on_commit_callbacks(execute=True)`, a bound and validated `AudioForm` (not a hand-built
   instance) so the `_post_clean` assignment is exercised and the snapshot is proven to hold the stored name,
   failure injection (`run_media_probe` raising after the new file is stored), a storage stub whose
   `get_available_name` returns its input unchanged, a storage stub whose `delete` raises so the
   `MediaIngestCleanupFailed` path is covered, and a direct `ingest_upload` call with a saved instance so the
   replacement branch is covered before any view uses it. ~210 lines. Prerequisite for V1 and the media
   replacement backlog item.
4a. Admin creates through the service. Add `ingest_policy` and `lock_uploads` to `MediaAdminConfig`, set them in the
   audio, video and transcript configs, route `add` and `chooser_upload` through `upload_lock` + `ingest_upload`, map
   exceptions to form errors. Tests: admin lock refusal, admin probe timeout with row and file cleanup, transcript
   add unaffected by the lock. Docs: `docs/operations/deployment.rst` (shared cache note covers admin), release note;
   mark observation 2 fixed in the security review. ~180 lines.
4b. Admin edit through the service. Route `edit` through `upload_lock` + `ingest_upload`; delete `delete_old_files`,
   the three `*delete_old_*_files` helpers and `tests/audio_views_test.py:512-520`. Tests: replacement failure keeps
   the old file and name, success deletes the old file only after commit (`tests/audio_views_test.py`,
   `tests/video_views_test.py`). Docs: release note; mark V1 fixed in the architecture review. ~180 lines. Needs 3, 4a.
5. Transcript byte cap. `validate_transcript_upload(file, *, max_bytes)` in `media_validation.py`, called from
   `TranscriptForm.clean_podlove/clean_dote/clean_vtt`; `_load_json` reads at most `max_bytes + 1`; register and
   document `CAST_TRANSCRIPT_UPLOAD_MAX_BYTES`. Tests: `tests/forms_test.py` over-cap podlove/dote/vtt, exact-cap
   accepted. Docs: `settings.rst`, release notes; mark observation 1 fixed. ~120 lines. Independent of 1-4.
6. Transcript edit through the service. `_handle_transcript_form_save` (`views/transcript.py:415-437`) calls
   `ingest_upload(form, policy=TRANSCRIPT_POLICY)` without the lock, so replaced `podlove`/`dote`/`vtt` files are
   deleted after commit instead of orphaned. Tests: `tests/transcripts/admin_endpoints_test.py`. ~100 lines. Needs 3.
7. `cast/safe_fetch.py`. Move `NoRedirectHandler`, `open_url`, `read_response_bytes`, `read_http_error_detail` (now
   taking `max_bytes`); add `FetchPolicy`, `fetch_bytes`, `FetchError`, `ResponseTooLarge`; Voxhelm client imports
   them, passes `MAX_VOXHELM_ERROR_BYTES` at call time and wraps errors; the five Voxhelm patch targets move. Tests:
   `tests/safe_fetch_test.py` (redirect refused, origin refused, size cap, error-body cap) plus the unchanged Voxhelm
   suite. Docs: `docs/architecture.rst` media pipeline paragraph. ~200 lines. Prerequisite for remote media, feed
   import and embeds.
8. Private-address policy and closing docs. `block_private_addresses` resolution check in `safe_fetch` (tests with a
   patched resolver), an "Upload and fetch safety" section in `docs/architecture.rst` for future importers,
   `BACKLOG.md` "media ingestion service" marked implemented, `backlog-analysis` cross-references. ~150 lines.

Every slice keeps `just check` green; 5 and 7 can be reordered freely. Slices 1-4b close observation 2 and V1, slice
5 closes observation 1, slices 3 and 7-8 are the prerequisites named in the brief.

## Risks and open questions

1. Shared lock key: (a) keep `cast:editor-media-upload:{pk}` everywhere, so an admin upload also makes a concurrent
   editor upload `rate_limited`; (b) separate keys. Recommendation: (a); one probe pipeline per user is the point,
   and (a) keeps `tests/api/editor_media_test.py:438` and `tests/video_upload_test.py:100`.
2. Setting names: (a) keep `CAST_EDITOR_MEDIA_*`, add `CAST_MEDIA_PROBE_SECONDS`; (b) rename with aliases. (a): no
   consumer sets the editor names, so a rename buys nothing.
3. Admin probe budget default 30 s. A site probing S3-hosted files over HTTP (`create_duration` uses `field.url`
   when absolute, `models/audio.py:191-199`) may exceed 30 s for duration plus chapters and see a new admin error;
   the wider atomic block also holds the transaction open that long. Options: 30 or 60. Recommendation: 30, noted.
4. Basename rename on every ingest: (a) on create and replace; (b) only on replace. Recommendation: (a); (b) leaves
   the same-named-create clobber on overwrite-capable storages, and no test or consumer asserts stored basenames.
5. Patch-target moves (eight `mocker.patch` strings): (a) accept; (b) indirection hooks. (a): (b) keeps the coupling.
6. Transcript replacement deletion (slice 6) turns orphaning into post-commit deletion: do it, release-noted.
7. Editor image uploads taking the lock: no; Wagtail images have their own size cap and no ffprobe.

## Non-goals

- Remote media import, feed import, embed blocks and editor media replacement themselves (this note only builds the
  primitives they need); connect-time IP pinning for `safe_fetch` (a hook is left for the first remote importer).
- `views/styleguide.py` remote fetches (`:1096`, `:1261`, `:1282`, `:1336`; operator-configured URLs, unbounded
  `response.read()`, redirects on): a follow-up `safe_fetch` consumer with `block_private_addresses=False`, not moved
  here because 20 test sites patch `styleguide_view.urlopen`.
- Changing the editor API contract, codes, messages or pagination; moving `forms.py` into a package (review D-item);
  registering the `CAST_VOXHELM_*` settings (X7).
- Backfilling durations or cleaning already orphaned storage files (`media_stale` covers that separately).

## Done when

- Editor API, admin add/edit/chooser upload and the transcript edit handler all reach storage through
  `media_ingest.ingest_upload`; `grep -rn "form.save()" src/cast/views/` returns only the speaker-mapping form.
- Admin audio/video uploads are refused while the same user has one in flight and their ffprobe/ffmpeg work is
  bounded by `CAST_MEDIA_PROBE_SECONDS`; transcript admin uploads take no lock.
- A failing replacement save leaves the previous file and the row pointing at it; a successful one deletes it only
  after commit, on overwrite-capable storages too (uuid-suffixed names; failure-injection and overwrite-stub tests).
- Transcript uploads above `CAST_TRANSCRIPT_UPLOAD_MAX_BYTES` are rejected before parsing, for JSON and VTT alike;
  `cast.safe_fetch` exists with tests and the Voxhelm suite passes unchanged in its assertions; the settings,
  deployment and architecture docs plus `docs/releases/0.2.65.rst` describe the new behavior.
- Security observations 1 and 2 and finding V1 carry fix notes; `BACKLOG.md` marks the seam implemented.

## Review log

- critical, accepted: lock out of `IngestPolicy`/`ingest_upload`; transport-owned `upload_lock`; `lock_uploads` flag.
- warning (transcript shares `MediaAdminViews`), accepted: `ingest_policy` factory; transcript edit row; slice 6 fix.
- warning (S3 overwrite defeats guard), accepted: `fresh_file_name` rename; snapshot-equal names never deleted; test.
- warning (setting registered too late), accepted: registration in slice 1; direct `ingest_upload` test in slice 3.
- warning (patch inventory), accepted: :353/:427, :304/:541 stay, direct calls, `urlopen` x4, :708, :512-520, :100.
- warning (slice 4 oversized), accepted: split into 4a (creates, config fields, lock) and 4b (edit, deletions).
- warning (anchors; video has no probe except), accepted: transcript model consumer, `forms.py:274-284`, video note.
- suggestion (styleguide urlopen), accepted: listed under Non-goals as a follow-up `safe_fetch` consumer.
- suggestion (`check_type=int` on probe seconds), accepted: no `check_type` for `CAST_MEDIA_PROBE_SECONDS`.
- suggestion (atomic `using`, m2m scope, `speakers`), accepted: stated in the Target design guard paragraph.
- critical, accepted (round 1): the guard cannot snapshot old names from the instance - `_post_clean` assigns the
  upload during `is_valid()`. `track()` now reloads the stored names from the database (the query
  `_delete_old_audio_files` already does), and slice 3 tests it through a genuinely validated form.
- critical, accepted (round 1): `_delete_file` suppresses every storage error (`file_replacement.py:170-172`), so a
  rollback built on it could never raise `MediaIngestCleanupFailed`. Rollback now uses a strict delete, post-commit
  deletion stays best-effort, and slice 3 covers the raising path with a failing-storage stub.
