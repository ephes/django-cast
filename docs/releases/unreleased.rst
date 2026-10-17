Unreleased
==========

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
