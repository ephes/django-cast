Unreleased
==========

- Make asset-freshness tests deterministic with explicit timestamps, including
  equal source/manifest times. Exercise first-publication number allocation on
  separate PostgreSQL connections, including independent podcasts and republish;
  include the numbering module in the existing opt-in PostgreSQL tox checks.

- Bound audio authorization and anonymous speaker ancestor, alias-source and
  restriction lookups to deduplicated batches of 500 paths/IDs. Audio reused by
  over 1,000 episodes retains full restriction checks and candidate ordering.
- Serialize glossary import validation and publication using the same podcast
  parent-row lock as transcript review and admin saves. Revalidate admin forms
  under that lock, reporting cross-term variant conflicts as validation errors.

- Update Vitest, coverage and mocker peers to 4.1.12, fixing the development
  mock-server advisories GHSA-qxg6-89mg-rqv8 and GHSA-xp26-3454-mjgp. The full
  npm lock audit now reports zero vulnerabilities (previously three moderate
  affected package nodes); shipped player code is unaffected.
- Audit the full JavaScript lock, including development packages, in an
  independent push/PR/scheduled CI job with read-only contents permissions.

- Resolve only uncached rich-text page links and retain localized relative and
  absolute URLs, including missing targets, in the context-local cache. Mixed
  batches reuse hits; language changes reset cached URLs and feeds stay absolute.
  Clear entries on Django request boundaries, including WSGI worker threads.
  Non-HTTP callers should clear the cache between independent renders.

- Filter public speaker aggregates through Wagtail public querysets and batch
  audio-anchor ancestors, aliases and restriction data. Preserve the granting
  page, authenticated restrictions, draft-editor access and private-cache headers.

- Reuse prefetched chapter marks in both public audio chapter readers, keeping
  chronological order and existing formatting. Batch contributor avatars and
  existing avatar renditions in post snapshots; missing renditions still generate.

- Build the glossary import identity index once, retaining per-entry validation.
  Publish only supplied fields, comparing their lookup values atomically and
  reporting concurrent edits as skipped conflicts. Omitted fields keep edits.

- Interpret ffprobe decimal seconds by place value, rounding to microseconds
  with ties to even; reject invalid or oversized durations through the existing
  probe error contract, using portable signed 64-bit microsecond storage bounds.
  Existing stored durations need a separate repair.
- Bound glossary JSON imports to 8 MiB and 10,000 entries before mutation,
  with concise read/decode diagnostics. Split larger imports into smaller files.

- Add an optional HTTP(S) playing-post permalink to shared player payloads.
  Share/copy links retain that source after navigation, with a connection-time
  fallback for legacy integrations. Apply URL start times only to a matching
  source; unrelated episode selection and overview cards no longer inherit them.
  Adopt the package and rebuilt assets together.

- Reject nonfinite and unrepresentable editor timestamps safely in speaker
  samples and voice-reference ranges, preserving source artifacts and valid
  fractions. Strip unsupported structured speaker/voice values from filtered
  public Podlove output while retaining approved labels and transcript text.

- Preserve chapter milliseconds through audio, player and chapters JSON, with
  fractional seeking and unchanged integer values for whole seconds. Treat
  oversized transcript numbers and clock arithmetic overflow as unusable times
  instead of failing the public transcript endpoint.

- Probe poster dimensions using ffprobe JSON for the first video stream,
  excluding attached cover art and separating diagnostics from JSON. Apply
  sample aspect ratio before rotation for anamorphic display geometry. Swap
  dimensions only for quarter
  turns of that stream; zero/half turns and encoded portraits retain their axes.
  Existing posters are not automatically regenerated.

- Respect native disclosure/media controls, prevented key events and composition
  before page-wide player shortcuts. Preserve exact Unicode cue text when
  highlighting lowercase-expanded matches, combining sequences and emoji.
  Consumers must adopt the rebuilt player assets.

- Bind lazy transcript hydration to its connection/controller, abort on
  disconnect, enforce a 15-second whole-request deadline, and validate all cues
  before installation. Failures allow a deliberate retry. Announce retryable
  playback failures accessibly while keeping AbortError silent. Adopt the rebuilt
  player assets with the package.

- Preserve newer comment drafts and reply targets while POST/save requests are
  pending. Serialize inline saves, ignore cancelled editors' late responses,
  and scope threaded Reply/Cancel by object. Edit/Delete now show accessible
  retry feedback for transport/parse/HTTP errors and a 15-second request deadline.
  Consumers must adopt the rebuilt comments bundle.

- Make future runs of private-storage migration 0078 verify unique copies on the
  selected database and defer reference-checked source cleanup until commit.
  Retain sources with multiple aliases and document rollback/orphan recovery;
  do not automatically rerun the migration on deployed databases. Stream runtime
  and migration 0084 transcript fingerprints in 64 KiB chunks without changing
  their identity.

- Fence queued Voxhelm completions by an immutable attempt identity and recheck
  ownership under the publication lock after downloads. Queue handoff now runs
  after commit on the generation database; rollback queues no work, and enqueue
  failures mark only the current attempt failed. Apply migration 0087 and update
  workers together; legacy tasks without identity are ignored and can be recovered
  through stale-generation retry.

- Validate Voxhelm polling/request/job durations as finite positive values up to
  one day, including direct client construction. Bound whole polling exchanges
  and sleeps by the elapsed job deadline, reject late success, and cap outstanding
  exchanges at four per process. Consumers must adopt the package and use a
  positive polling interval.

- Prevent caching of owner audio/video list/detail responses, all editor API
  responses (including previews and structured errors), and the staff-only
  comment training corpus. They now use ``Cache-Control: private, no-store``
  and vary on ``Cookie`` and ``Authorization`` so revoked credentials or
  permissions are checked again. Public media cache policies are unchanged.
  Consumer sites must adopt the updated package for this to take effect.

- Add behavioral tests for quickstart management subprocesses, both superuser
  modes, CLI setup/refusal/cleanup ordering, and read-only media-size reporting
  using temporary projects and synthetic storage. Document these contracts and
  the quickstart tests' independence from its existing coverage omission.

- Serialize shared glossary variant additions using current term/contributor
  state, including first-term creation and contributors shared between shows.
  Invalid UTF-8 or excessive JSON nesting now yields a bounded transcript
  artifact error and HTTP 400 in the editor, before editorial writes; corrupt
  originals and public artifacts remain intact for replacement.

- Reject stale speaker/glossary editor forms with HTTP 409 and a reload message.
  Conditional artifact replacement protects concurrent service edits and cleans
  up conflicted staged files without overwriting unrelated artifacts. Speaker
  mapping discovery now serializes per transcript and reads current source and
  approval state, with idempotent unique-label creation.

- Synchronize chapter link/image edits and explicit clears as well as titles.
  Chapter replacements now validate unique starts and audio ownership and apply
  atomically, with serialized writers on SQLite and PostgreSQL. Failed saves
  preserve the previous complete chapter set; unchanged markers are not saved.
  Title-only form/API/probe sources retain stored URLs. Duplicate starts in chapter
  text produce a field validation error.

- Make editor image upload failure tests portable across supported Django
  versions by injecting INSERT failures through the SQL execution wrapper,
  after the uploaded file has been written.

- Test Wagtail 8.1 explicitly alongside 8.0, including the v3 experiment,
  PostgreSQL publication locks, and 100% coverage on 8.0.1 and 8.1. The experiment
  now checks 8.1's discriminated block schemas and workflow route inventory.
- Resolve image permissions lazily through Wagtail's public policy registry,
  avoiding the deprecated image permission import on Wagtail 8 while retaining
  the Wagtail 7 fallback.

- Editor image uploads now use short generated storage names and transactional row/tag
  registration through the shared media ingestion service. Failed saves remove
  the request-owned image file; existing same-named images are preserved. Cleanup
  failures are logged, retain the original save error as their cause, and return
  the standard ``cleanup_failed`` JSON error. Long filenames cannot truncate away
  the unique suffix.

- Editor media collection IDs now require positive integers or canonical decimal
  strings. Fractional/nonfinite numbers, booleans, null, and noncanonical strings
  return validation errors instead of being coerced to another collection.

- Move transcript sanitization and copy-on-write speaker transforms into the
  Podlove, DOTe and WebVTT format modules, and episode speaker visibility policy
  into ``cast.transcripts.visibility``. Historical imports from
  ``cast.transcript_sanitization`` remain available as re-exports; public and
  editor-preview behavior is unchanged.

- Integrate release-branch fixes into the develop trunk, preserving the editor
  API episode automation, paired Voxhelm credentials, dependency security floors,
  and combined WebVTT voice spans with visible speaker names. Glossary corrections
  preserve the visible name, so applying corrections and known-speaker suggestions
  in either order produces the same transcript.

- Applying a known-speaker suggestion to a WebVTT cue that still has a generic
  ``Speaker N:`` prefix now treats the prefix like a rename:
  ``Speaker 1: hi`` becomes ``<v Bob>Bob: hi</v>`` instead of
  ``<v Bob>Speaker 1: hi``, so the old label no longer stays in the public
  cue text, and public sanitization of a hidden name strips the repeated
  ``Bob:``. Clearing a suggestion on such a cue removes the ``Speaker N:``
  prefix, matching the cleared Podlove and DOTe speakers; a payload line that
  only held the speaker label is removed instead of left blank, which would
  have ended the cue.
- Behaviour change: when neither the request nor the blog resolves a Wagtail
  site, the repository's site fallback now uses the ORM and picks the default
  site, then the lowest primary key, instead of an unordered raw SQL query that
  returned an arbitrary row. An empty ``wagtailcore_site`` table now raises
  ``ImproperlyConfigured`` instead of leaving the site out of the repository
  data (which failed later with a ``KeyError``). Create a Wagtail ``Site``
  before serving blog indexes or feeds.
- Blog index and feed repositories no longer fall back to key-sniffing for
  posts or blogs without a ``type`` discriminator; ``deserialize_blog`` now
  raises ``KeyError`` for such data, as the post deserialization already did.
  The cachable data is built and consumed within one request and always
  carries the discriminator, so the legacy branches were unreachable.
- Public WebVTT sanitization now matches voice tags with a stack per cue.
  Before, a hidden speaker's voice span that contained another voice span
  (``<v Ann>Ann: x <v Zed>y</v></v>``, as renaming or applying a suggestion to
  ``Speaker 1: x <v Speaker 2>y</v>`` produces) left a stray ``</v>`` in the
  public output, and an allowed inner speaker could lose its closing tag.
  Hiding an opening-only voice now also removes its ``</v>`` on a later line of
  the same cue.

- Bring the architecture and settings docs in line with the code: ``Blog``,
  ``Podcast`` and ``Season`` live in ``models/index_pages.py``, the "Code
  Organization" tree lists every module, and ``CAST_REPOSITORY = "default"`` is
  described as the ORM plus an in-request serialize/deserialize round trip (no
  cache, no hand-optimized SQL). A new docs test checks that module paths in the
  docs exist and that the tree stays complete.
- Resolve Voxhelm API base and token as a pair from one configuration level.
  Incomplete pairs no longer inherit deployment credentials. Move mixed-level
  credentials to one level before upgrading; changing the Wagtail API base
  requires re-entering its token. Saving with both credential fields blank
  removes the site pair so deployment credentials can be used.
- Prepare a complete podcast episode through the editor API without Wagtail
  admin steps:

  - ``POST /api/editor/media/audios/`` now accepts
    ``transcript_diarization_mode=enabled``. The mode is validated before the
    file requirement, so a file-less request feature-detects support (no
    ``transcript_diarization_mode`` error); unknown modes return
    ``invalid_choice`` instead of ``unsupported``.
  - New ``GET``/``PATCH /api/editor/media/audios/{id}/``. ``PATCH`` updates
    ``title``, ``subtitle``, ``tags``, and ``transcript_diarization_mode`` and
    adds or replaces one audio file format per request (``m4a``, ``mp3``,
    ``oga``, ``opus``) with the upload validation, probe budget, and upload
    lock. Existing chapter marks are kept unless ``chaptermarks`` is sent.
  - Episode create, read, and ``PATCH`` responses include ``contributors``, and
    create/``PATCH`` accept an ordered ``contributors`` list referencing
    contributors by ``id`` or ``slug`` with an optional ``role``. New
    ``GET /api/editor/contributors/`` lists assignable contributors.
  - New ``GET``/``POST /api/editor/episodes/{id}/transcript/`` reports and
    requests Voxhelm transcript generation with the Wagtail action's
    permissions (``write`` scope for ``POST``). ``POST`` returns ``202`` and is
    idempotent while a generation is active; missing configuration returns
    ``409 voxhelm_not_configured``. The status reports effective diarization
    and known-speaker settings with their source, generation state, speaker
    labels as shown in the editor preview, speaker mappings, and known-speaker
    suggestion counts.

- Editors now see approved speaker names when previewing an unpublished
  episode. Transcript requests authorized through edit permission use the
  episode's latest draft as the speaker-label anchor; public output, anonymous
  access, and live-episode labels are unchanged. Editors can also reach audio
  and transcripts that only the latest draft of an unpublished episode
  references (for example ``podcast_audio`` changed after creation), so the
  preview player works before publication; these responses stay private.
- The Wagtail Voxhelm settings now label the diarization and known-speaker
  choices as "Not set here" (inherit the Django setting or environment
  variable), "Enabled for this site", and "Disabled for this site", and show
  the value each currently resolves to and its source. An explicit site value
  still overrides the environment; a site that stored "No" before keeps
  overriding an environment ``true`` until it is set back to "Not set here".
  ``cast.voxhelm`` gains ``resolve_setting()`` and ``resolve_bool_setting()``,
  which also return the configuration level.
- Keep Cast's cache-aware rich text page link handler active regardless of
  import order. The ``register_rich_text_features`` hook now runs after
  Wagtail's core features. Before, Wagtail's default handler could replace it
  when ``cast.wagtail_hooks`` was imported before Wagtail searched for hooks
  (seen with Wagtail 8.1), so repository-rendered pages and feeds queried the
  database for internal page links.
- Raise the Django REST Framework security floor to 3.18.2 for
  CVE-2026-114136, CVE-2026-114137 and CVE-2026-114138, and the Pillow floor
  to 13.0.0 for the 39 advisories the strict floor audit reports against
  12.3.0. Pillow 13 is a major release; refresh application locks that retain
  earlier DRF or Pillow versions. Both strict dependency audit jobs are kept.
- ``Transcript.rewrite_speaker_labels()`` now also renames generic
  ``Speaker N:`` cue prefixes in the stored WebVTT file. Before, the editor
  offered these labels for renaming, but only ``<v ...>`` voice spans were
  rewritten, so the stored WebVTT kept the old prefix while Podlove and DOTe
  showed the new name. A renamed prefix becomes a closed WebVTT voice span
  that repeats the name in the cue text (``Speaker 1: text`` becomes
  ``<v Alice>Alice: text</v>``), so the name stays visible in players that do
  not show voice names and can still be renamed and sanitized. Renaming again
  replaces the repeated ``Alice:`` together with the voice label instead of
  adding a second prefix, and public sanitization of a hidden label removes
  the repeated name from the cue text as well as the voice tags. Applying or
  clearing known-speaker suggestions on such a cue replaces or drops the
  repeated name together with the voice label. Read-time
  public mapping and sanitization now share the WebVTT speaker patterns and
  rewriting with ``cast.transcripts``: public WebVTT output shows a mapped
  prefix as ``<v Alice>Alice: text</v>`` instead of ``Alice: text``, and an
  indented ``Speaker N:`` prefix is now mapped or stripped, as detection
  already did.
