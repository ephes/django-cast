Unreleased
==========

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
