.. _audio_and_transcripts:

*********************
Audio and Transcripts
*********************

Django Cast provides comprehensive audio support for podcasting, including multiple format handling, chapter marks, and transcript integration with the Podlove Web Player.

.. _audio_overview:

Audio
=====

You can upload audio files to the server and play them back in the browser.

Audio Models
------------

Audio files are represented by the `Audio` model. Audio files have a `title`, a
`subtitle`, `tags` and four file fields pointing to the file in different audio formats:

* `m4a` - AAC, works best on Apple/iOS devices
* `mp3` - MP3, works everywhere, but has no time index so the whole file has to be downloaded before playback can start
* `oga` - OGG Vorbis, maybe remove this one because apple is now adding support for opus, too
* `opus` - Opus, better quality per bitrate than all other formats, but not as well known as the others

Since podcast feeds only support one audio file per episode, there is one feed
per audio format. The feeds are generated automatically and can be found at
`feed/podcast/<audio_format>/rss.xml`.

Playback
--------

For playback of audio content `Podlove Web Player <https://podlove.org/podlove-web-player/>`_
version 5 is used.

.. Hint::

    Currently supported features:

    * Chapter marks
    * Download button

.. note::

    The Bootstrap templates defer Podlove player initialization on list pages by
    setting ``data-load-mode="click"`` on the player element. Remove the
    attribute in your templates to keep automatic initialization behavior.

.. note::

    The Podlove Web Player theme is configured via
    ``/api/audios/player_config/``. You can override the default tokens and
    fonts per theme using the ``CAST_PODLOVE_PLAYER_THEMES`` setting.

.. _custom_audio_player:

Custom Audio Player
===================

As an alternative to the Podlove Web Player, django-cast ships an optional
**custom audio player**: a dependency-free vanilla-TypeScript web component that
couples three concerns — playback transport, an interactive transcript, and
chapter navigation. It renders immediately from a sanitized JSON payload inlined
into the page, adapts to the host site's colors via CSS custom properties (light,
dark, and forced-colors), and adds no runtime dependencies and no
hover/click-to-load facade.

Enabling
--------

Set ``CAST_AUDIO_PLAYER`` to choose the player:

* ``"podlove"`` (default) — the Podlove Web Player, unchanged.
* ``"custom"`` — the custom web-component player.

.. code-block:: python

    CAST_AUDIO_PLAYER = "custom"

The custom player renders **only on the episode detail path**, at the
StreamField ``audio`` block render location (where Podlove renders on
server-rendered themes). List/overview cards render no audio player in custom
mode (the deliberate "fewer players on overview" outcome), feeds are unchanged,
and the cast-vue SPA ``podlove_players`` API path is untouched.

The detail and list contexts expose two derived booleans —
``use_podlove_player`` and ``use_custom_audio_player`` — that themes use to gate
their asset/preconnect includes. The component is built and shipped by
django-cast and included with the ``cast`` app:

.. code-block:: django

    {% vite_asset 'src/audio/custom-player.ts' app="cast" %}

Inline metadata and the lazy transcript
---------------------------------------

The detail page inlines only the small player payload — audio metadata, sources,
and chapters — as JSON (via ``json_script``). The transcript is **never inlined**.
Instead the payload carries a transcript endpoint URL (or ``null`` when the audio
has no transcript), and the player fetches the cues **lazily**: once, the first
time the reader opens the Transcript panel. A collapsed transcript triggers no
fetch, and the detail-page render never builds or sanitizes the transcript at
all — keeping the page small and the render cheap.

The transcript endpoint is ``cast:api:audio_player_transcript`` at
``/api/audios/<pk>/player-transcript/``. It takes a ``post_id`` query parameter
(to establish the episode/contributor context for sanitization), is public-read,
validates that the post is live and owns the audio, and returns the normalized,
sanitized ``{"cues": [...]}`` shape — **never** the raw Podlove file. The cue
normalization and the public speaker-label sanitization (the same applied to the
Podlove API output) run only in this endpoint, so non-public speaker labels and
raw ``podlove_data`` never leak.

Public transcript responses include a strong ``ETag`` and a short shared-cache
freshness window (``Cache-Control: public, max-age=30, must-revalidate``).
Browsers, reverse proxies, and CDNs may reuse the response for 30 seconds, then
must revalidate it; unchanged cues receive a small ``304`` while speaker
corrections replace the cached response after at most that short window.
Restricted or preview responses remain private and uncacheable.

Theming tokens
--------------

The player's structural CSS uses these CSS custom properties (with fallbacks);
host sites theme the player by mapping them, without changing the component. In
practice the only token most sites need to set is ``--cast-player-accent`` — the
surface, line, highlight, and focus colours are derived from it (as translucent
accent overlays) so highlights stay visible on both light and dark backgrounds:

* ``--cast-player-accent`` (fallback ``#2d8260``) — the brand accent; drives the
  play button, progress fill, timecodes, current-cue/chapter highlight, and
  search marks.
* ``--cast-player-fg`` (``CanvasText``) and ``--cast-player-bg`` (``Canvas``) —
  text and the share-dialog background.
* ``--cast-player-muted`` (``#6b7280``) — secondary text.
* ``--cast-player-on-accent`` (``#fff``) — text/icon colour on accent fills.
* ``--cast-player-progress-track`` (translucent ``currentColor``) — the unfilled
  seek track.
* ``--cast-player-surface`` / ``--cast-player-line`` (derived from accent) —
  panel background and borders.
* ``--cast-player-focus`` (``var(--cast-player-accent)``) — the focus ring.
* ``--cast-player-mono`` — the monospace stack for timecodes.

A ``@media (forced-colors: active)`` block keeps borders, the focus ring, and the
current-cue marker legible in high-contrast mode, and a
``@media (prefers-reduced-motion: reduce)`` block disables transitions. The
transcript and chapter elements read their data from the controller, so a theme
can relocate them anywhere on the detail page by moving the
``<cast-transcript for="...">`` / ``<cast-chapters for="...">`` elements while
keeping the same ``for=`` id. The transcript is a collapsible panel (search, a
follow-along auto-scroll toggle, current-cue highlight, and a share-with-time
control on the transport are built in).

.. _transcript_overview:

Transcripts
===========

You can upload transcript files to the server and display them
alongside the audio player. They will be also included in the feed
and can be used by podcast clients to display the transcript while
listening to the episode.

Transcript Models
-----------------

Transcript files are represented by the `Transcript` model. Transcripts have an
audio file they belong to, a `podlove` field that contains the transcript in
the form that the `Podlove Web Player <https://podlove.org/podlove-web-player/>`_
can use. And two other file formats that are used for to be referenced in the
feed:

* `vtt` - WebVTT, a subtitle format in plain text
* `dote` - DOTE, a json transcript format. Each line's ``startTime`` and
  ``endTime`` must be ``HH:MM:SS,mmm`` (``.`` also works before the fraction,
  which has one to three digits); uploads with other timestamps are rejected.

Transcript admin permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Wagtail transcript administration requires the relevant Transcript collection
permissions and permission to **choose** the linked Audio. Add and upload forms
only offer audio the current user may choose, and reject forbidden audio IDs
submitted directly. Editing a transcript cannot retain or replace its audio
with an object the user is not allowed to choose.

Existing transcripts linked to inaccessible audio are also excluded from the
user's transcript admin lists and choosers; direct admin access is denied.
Grant delegated transcript editors Audio choose permission on the required
collections as well as their Transcript permissions. A user with access to
both collections can manage a transcript whose collection differs from its
audio's collection. This change does not move existing objects or rewrite
their relationships.

Transcript output and storage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Podlove, WebVTT, and DOTe transcript artifacts are public transcript output.
They are used by transcript pages, podcast feeds, podcast clients, and the
custom audio player. Public JSON, WebVTT, PodcastIndex, and HTML transcript
responses are still served through django-cast views that authorize the related
episode/audio and sanitize public speaker labels, but the stored artifact
content itself is publishable for public episodes.

Authorization serves an object only when it is anchored to a live episode/post
whose Wagtail view restrictions the request satisfies (the *public path*), or
when the requesting user has ``can_edit`` on a referencing page (the *editor
path*, which covers Wagtail preview and never-published drafts). A supplied
``episode_id``/``post_id`` anchor must actually reference the requested object
and satisfy one of those paths; a missing, mismatched, or non-public anchor is
rejected rather than silently ignored. Every denial returns ``Http404`` (never
``403``) so object existence is not leaked.

The Podlove audio detail API marks responses authorized through a draft or
restricted page as ``Cache-Control: private, no-store`` and varies on ``Cookie``
and ``Authorization``. This keeps Django's full-site cache from replaying a
previously authorized response after credentials or group membership are revoked.
When multiple anchors are supplied, any draft or restricted granting anchor
makes the response private. Unrestricted public responses retain their existing
cache behavior. The same private-response policy applies to the raw Podlove JSON, PodcastIndex
JSON, WebVTT, and chapters views, using the page that grants object access.
The HTML transcript views retain their existing response behavior.
On deployment, purge existing responses for these media endpoints from
application and downstream caches: the new headers prevent future private
response storage but cannot evict responses stored before the upgrade.
Previously unrestricted public responses keep their existing cache lifetime;
adding a restriction or unpublishing a page does not invalidate those stored
responses. Purge the affected media URLs when immediate removal is needed.

Configure ``STORAGES["cast_public_transcripts"]`` for production when transcript
artifacts should use a dedicated public storage backend or prefix. If that alias
is omitted, django-cast uses an explicitly configured ``cast_private_media``
alias for compatibility with deployments that already adopted the temporary
private-storage behavior; if neither alias is configured, transcript artifacts
use Django's default storage. Private editorial sidecars, such as known-speaker
suggestions, use the private voice-reference storage described below instead.

Voxhelm Integration
-------------------

If your audio files are available through absolute HTTP(S) URLs, you can use
the Wagtail admin or the built-in ``generate_transcripts`` management command
to request a transcription from Voxhelm and populate all three transcript
artifacts on the existing ``Transcript`` model.

In Wagtail admin, editors with the required page/media permissions can trigger
transcript generation directly from:

* an episode edit view
* an audio edit view

The "Generate transcript" action only appears when Voxhelm is configured for
the request's site — the API base URL and API key must resolve through site
settings, Django settings, or environment variables. Transcript generation
status stays visible on both edit surfaces even when the configuration is
later removed.

The admin request now returns after the Voxhelm batch job has been submitted
and a local completion task has been queued. Editors see local
queued/running/succeeded/failed status on the same Episode and Audio edit
surfaces while the background worker polls Voxhelm, downloads the artifacts,
and updates the ``Transcript`` model.

Site admins can manage the Voxhelm API base URL, API token, and optional
model/language defaults in ``Settings -> Voxhelm settings``.

When an existing API token is stored in Wagtail, the token field is intentionally
blank when you reopen the settings form. If the help text says that a token is
configured, keep the API base URL set and unchanged and submit the form with
the token field blank to keep the stored token, or enter a new token to replace it. Changing the API base URL requires entering
the token again. To use deployment credentials instead, clear both fields
together; clearing the base and leaving the token blank removes the stored pair.

Production sites can also keep Voxhelm credentials in deployment-managed Django
settings or environment variables instead of the Wagtail database. django-cast
looks up site-level Wagtail values first, then Django settings, then environment
variables. Use ``CAST_VOXHELM_API_BASE`` and ``CAST_VOXHELM_API_KEY`` for the
required service URL and bearer token; optional defaults use
``CAST_VOXHELM_MODEL``, ``CAST_VOXHELM_LANGUAGE``, and
``CAST_VOXHELM_DIARIZATION_ENABLED``. If the token should be managed as a
deployment secret, leave both Wagtail credential fields blank and provide both
``CAST_VOXHELM_API_BASE`` and ``CAST_VOXHELM_API_KEY`` to the web process and
transcript worker at the same level (Django settings or environment).

The API base and token resolve as a pair from one level: Wagtail site settings,
then Django settings, then environment variables. Any nonempty credential at a
level selects that level; an incomplete pair is not configured and never
inherits the missing credential. Existing installations that mix levels must
move both credentials to one level before upgrading.

Each audio object also has a transcript diarization mode. The default
``inherit`` mode keeps using the site/global Voxhelm diarization setting for
future transcript generation. Editors can set an individual audio to
``enabled`` to request diarization even when the site/global default is off, or
to ``disabled`` to submit future Voxhelm jobs without the diarization payload or
speaker-count hint. The setting belongs to the shared audio transcript, so
changing it can affect every episode that uses the same audio.

Disabling diarization is non-destructive. It keeps transcript text, timestamps,
and stored Podlove, DOTe, and WebVTT files in place, but public transcript
surfaces hide stored speaker labels for that audio. Re-enable the mode later to
allow existing labels to appear again when they pass the live-contributor
sanitizer.

To make the non-blocking Wagtail flow work, install the optional
``transcript-worker`` extra, configure Django Tasks with the database backend,
and run a worker alongside Django. The extra requires a Wagtail/django-tasks
combination compatible with ``django-tasks-db`` 0.12; Wagtail 7.0 LTS uses
``django-tasks`` 0.7 and is not compatible with that database backend. Keep the
global ``default`` backend immediate so third-party apps that decorate tasks at
import time do not pull in the database backend before app loading has finished:

.. code-block:: bash

    uv pip install "django-cast[transcript-worker]"

.. code-block:: python

    INSTALLED_APPS += ["django_tasks_db"]

    TASKS = {
        "default": {
            "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
        },
        "cast_transcripts": {
            "BACKEND": "django_tasks_db.DatabaseBackend",
        },
    }

.. code-block:: bash

    python manage.py db_worker --backend cast_transcripts --worker-id cast-transcripts

Use a stable, distinct ``--worker-id`` for each deployed site. See
:doc:`../operations/deployment` for deployment examples.

.. code-block:: bash

    # Operator fallback
    python manage.py generate_transcripts --episode-id 42

django-cast now consumes Voxhelm-owned Podlove, DOTe, and WebVTT transcript
artifacts directly from the batch job result and persists them onto the
existing ``Transcript`` model without local format conversion.

Speaker labels are assigned per transcript segment at the transcription
backend's own segmentation granularity. Voxhelm groups speech into multi-second
ASR segments and labels each segment with a single (dominant) speaker, so during
rapid exchanges a segment can span more than one turn -- for example a brief
"Welcome, <name>" from a host at the start of a guest's first segment. The whole
segment then carries one speaker label, so the displayed speaker can be
approximate for a second or two until the next segment boundary, where it
"catches up". django-cast stores and renders the backend's segments as-is and
does not re-split them by turn; finer turn alignment (or word-level speaker
timing) is a transcription-backend concern. Re-mapping labels or applying
known-speaker review changes *which* name a segment shows, not where segment
boundaries fall.

When generated transcripts include diarization speaker labels, the Wagtail
transcript edit form lets editors map those raw labels to episode contributors
or one-off display names. The mapping form shows short transcript samples for
each speaker and, when the audio file is playable from the admin, timestamp
controls that seek the audio preview to the sample position. Saving a mapping
stores reviewable mapping rows on the transcript; the stored Podlove, DOTe, and
WebVTT artifacts remain unchanged. Mappings are reviewed against the transcript
artifacts as received: ``Transcript.source_fingerprint`` holds the hash of the
Podlove, DOTe, and WebVTT files stored by a Voxhelm import or an admin upload
(any save that stores new artifact files). Applying known-speaker suggestions
and ``Transcript.rewrite_speaker_labels`` change the files but not this
fingerprint, so approved mappings stay current. If a transcript is regenerated
or manually re-uploaded, old approvals are kept for review but are marked as
needing review, labels that disappeared become inactive history, and new labels
start unmapped. Code that rewrites the public files from the received ones
saves with ``save_transcript_with_derivations(transcript,
preserve_source_fingerprint=True)`` to keep approvals; code that replaces file
bytes in place under the same file name calls
``Transcript.mark_artifacts_received()`` before saving.

Generated transcript text is stored with the shared audio file and can appear
on already published episodes as soon as generation completes. Public speaker
metadata is stricter: player JSON, public transcript JSON, PodcastIndex JSON,
HTML transcript pages, and supported WebVTT speaker labels apply approved
speaker mappings at read time and then sanitize the result. Contributor
mappings are public only when the contributor is visible on the live episode;
approved one-off display names can be public without creating reusable
contributor snippets. Draft-only contributor mappings, hidden or deleted
contributors, stale approvals, disabled diarization mode, and unmapped labels
such as ``Speaker 1`` are hidden from public output. If a transcript is not
connected to any live episode yet, public transcript endpoints expose no
speaker labels. The stored transcript files are not rewritten by this mapping
or sanitization step. One-off display names cannot duplicate a raw transcript
speaker label; this keeps an approved one-off name from accidentally allowing an
unmapped anonymous label with the same text.

The explicit ``Transcript.rewrite_speaker_labels(mapping)`` API rewrites stored
artifacts. For WebVTT it renames both voice tags and generic ``Speaker N:``
prefixes inside cue payloads. Renamed prefixes become closed voice spans per payload line so
subsequent renames and public label sanitization continue to work. Cue text and
line endings are preserved.
Headers, cue identifiers, and non-cue text remain unchanged.

Private contributor voice references
------------------------------------

Anonymous diarization clusters voices but cannot reliably identify a known
recurring speaker, and the speaker-mapping form can only rename clusters that
diarization actually produced. To support known-speaker recognition, a
contributor can carry private *voice references*: reviewed clean-solo speech
that a known-speaker backend can use to recognise that contributor's voice.

Voice references are sensitive, admin-only editorial data. They are **never**
exposed through public contributor APIs, podcast feeds, theme context,
repository serialization, static exports, or public transcript output. Manage
them from the Wagtail contributor snippet under *Voice references (private)*.

Each reference is either an uploaded clean-solo clip **or** a source range into
existing audio, never both:

- A *source range* points at an existing ``Audio`` object with
  ``start_seconds`` and ``end_seconds`` (start must be before end).
- An *uploaded clip* is stored through a protected storage backend. Configure a
  non-public backend under the ``"cast_voice_references"`` alias in
  ``STORAGES`` for dedicated voice-reference storage. When the alias is absent,
  django-cast falls back to the private media backend instead of default public
  media storage.

References start as ``pending`` and must be explicitly ``approved`` before they
can be sent to a known-speaker backend. Approval requires confirming contributor
consent (``consent_confirmed``). The remaining statuses are ``disabled`` and
``rejected``, both retained for audit but never used. Hiding or disabling a
public contributor never deletes reference material; a hidden contributor is
also excluded from known-speaker use for public transcripts unless an editor
explicitly opts a reference in with ``allow_for_hidden_contributor``.

For diarized Podlove transcripts, editors normally create source-range
references from the Wagtail transcript edit view instead of typing raw seconds
in the Contributor snippet. After mapping speaker labels to episode
contributors, the transcript view shows *Voice-reference candidates*: contiguous
solo-looking speaker runs with start, end, duration, and transcript text. The
candidate picker splits same-speaker runs across large untranscribed gaps, so a
proposed range does not silently span unrelated audio. The candidate buttons use
the transcript audio player and stop playback at the candidate end time so the
range can be auditioned before saving. Saving without confirmed consent creates
a ``pending`` reference; creating an ``approved`` reference requires the editor
to explicitly tick the consent confirmation in that row. Existing matching
source-range references are shown as already present and are not duplicated.

Voice references store only reviewed reference material and editorial state.
They deliberately do **not** store model-specific voice embeddings, because
embeddings are owned by the transcription backend and would become stale when
that backend changes its embedding model.

Known-speaker recognition
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Enable known-speaker recognition with ``CAST_VOXHELM_KNOWN_SPEAKER_ENABLED`` or
the site-level Voxhelm setting. When enabled, a diarized transcript-generation
request for an episode also sends the approved voice references of that
episode's expected contributors to Voxhelm as known-speaker reference material.
Only approved references are sent, and hidden contributors are excluded unless a
reference explicitly opted in. References are delivered as source ranges into
existing audio or, when the protected storage backend can provide an absolute
temporary URL, as uploaded clips. Uploaded clips on no-URL private storage are
kept private and skipped for automatic handoff; use source ranges for those
references. References are never public profile URLs.

The references come from the episode the audio belongs to. A request that names
only the audio, such as ``generate_transcripts --audio-id``, resolves that
episode itself when the audio belongs to exactly one episode. If no references
can be sent, because the audio is shared by several episodes or has none, or
because no assigned contributor has an approved usable reference, the request
still runs but returns anonymous diarization labels only. django-cast then logs
a warning on ``cast.voxhelm.service``, and ``generate_transcripts`` prints it.

Voxhelm classifies the transcript segments against those references and returns
per-segment *suggestions*: the most likely contributor, a candidate list,
confidence, a margin, an uncertainty flag, and the raw anonymous diarization
label. django-cast stores these as a private ``Transcript.speakers`` sidecar in
protected storage. The sidecar uses the same private storage selection as voice
references, falling back to the private media backend when no dedicated
``"cast_voice_references"`` alias is configured. They are reviewable editorial
state and never appear in public transcript output, feeds, theme context, or
APIs.

Known-speaker results are suggestions, not final identity. Voxhelm leaves the
public Podlove, DOTe, and WebVTT artifacts unlabeled for known-speaker jobs, so
no speaker identity is shown publicly until an editor reviews and approves the
suggestions. Uncertain or low-margin segments are flagged for review rather than
applied automatically; the one exception is an unambiguous guest without a
voice reference, described below.

The Wagtail transcript edit view shows a known-speaker review panel with the
confident and uncertain suggestion counts and the confident speaker
distribution. The bulk *Approve and apply confident suggestions* action writes
resolved speaker names into the public Podlove ``speaker``/``voice``, DOTe
``speakerDesignation``, and matching WebVTT cue voice labels, matched to
transcript segments or cues by start time. Confident suggestions are used
directly; the Wagtail action explicitly leaves uncertain segments unchanged for
review, apart from the guest naming described below. Programmatic callers retain the existing smoothing default and should
pass ``smooth=False`` to
``Transcript.apply_known_speaker_suggestions(...)`` when they need the same
confident-only behavior. Smoothing fills uncertain gaps from the surrounding
confident speaker so the public transcript has continuous labels, but it can
misattribute a rapid hand-off between confident segments from the same person.

A guest without a voice reference gets no suggestions, but diarization still
separates their speech under its own raw label. Applying suggestions names that
label after the guest automatically when the assignment is unambiguous:

- the audio belongs to exactly one episode, and exactly one of its assigned
  contributors is missing from the sidecar's ``known_speakers`` list (the
  contributors references were sent for, compared by display name), and that
  contributor is visible;
- exactly one raw diarization label is tied to no known speaker, and every
  speaker references were sent for is tied to a label of their own.

The label-to-speaker map comes from the sidecar summary's
``raw_diarization_labels`` (written by Voxhelm 0.1.7 and later). For older
sidecars django-cast rebuilds it with the same vote Voxhelm uses: confident
segments accepted on their own voiceprint vote for their speaker, and a label
belongs to a speaker when at least five segments vote and 90 % agree. Then the
uncertain segments on the leftover label get the guest's name, with or without
smoothing. Segments flagged as mixed speakers are not named by this rule (with
smoothing they are still filled like any other gap), confident suggestions are
unchanged, and explicit editor decisions still take precedence. In every other case, for example two
contributors without references or two leftover labels, the guest's segments
stay blank rather than risk a wrong name.

Editors can also review individual segments in the same panel. For each
segment they can keep the bulk result, choose a speaker from the returned
known-speaker candidates or episode contributor names, or leave the segment
blank. These per-segment decisions are stored additively as private
``editor_decision`` metadata inside the ``Transcript.speakers`` sidecar, so the
raw Voxhelm suggestion fields remain available for audit and re-application.
Explicit segment decisions take precedence over the confident/smoothed bulk
result, and blank decisions clear matching Podlove, DOTe, and WebVTT speaker
labels for that start time. Public transcript sanitization is unchanged:
corrected names are still exposed only when they match live public contributor
assignments.

.. _transcript_glossary:

Transcript glossary
-------------------

Speech recognition cannot spell names and technical terms it has never seen
("John" for Jon, "Gunacorn" for Gunicorn). The transcript glossary holds the
correct spellings and the misspellings to replace. It has three sources:
contributor variants, show terms per podcast, and terms derived from each
episode's show notes. Listed misspellings are replaced automatically after
each Voxhelm import (see :ref:`transcript_glossary_corrections`); everything
else becomes a proposal for an editor. The review of proposals in the
transcript admin follows in a later release.

Contributor variants
~~~~~~~~~~~~~~~~~~~~

The contributor snippet has a private *Transcript glossary* field,
``transcript_variants``, with one ``variant => replacement`` pair per line:

.. code-block:: text

   John Gould => Jon Gould
   John => Jon
   Jon Goold

A line without ``=>`` is replaced by the contributor's display name. Give an
explicit replacement for a first name, so that "John's" becomes "Jon's" rather
than "Jon Gould's". Variants of a contributor apply only to transcripts of
episodes that credit that contributor, so they may be common words such as
"John". Saving refuses lines with more than one ``=>``, an empty side, a
variant that equals its replacement (ignoring case and spacing), or a variant
listed twice with different replacements. The field is internal: public
APIs, feeds and the cached contributor data leave it out. Theme templates
receive the contributor objects themselves, so a template could still read
it; themes should not render it.

Show terms
~~~~~~~~~~

*Snippets → Transcript glossary terms* holds the terms of each podcast,
filterable by podcast and searchable by term and variant. A term is the
correct spelling (``term``), optionally with misspellings (``variants``, one
per line) and internal ``notes``. A term without variants is a known correct
spelling; each variant is meant to be replaced by the term in every transcript
of that podcast, so list only phrases that are always wrong. Saving refuses:

- a second term of the same podcast that differs only in case or spacing;
- a variant equal to its own term or to another term of the podcast;
- a variant that already belongs to another term of the podcast, and a term
  that is another term's variant;
- a single-word variant that is a common word in the podcast's transcript
  language ("rough" for Ruff, "kind", "copier"). Such errors need a decision
  in context, not a show-wide replacement.

The transcript language is the Voxhelm language hint
(``CAST_VOXHELM_LANGUAGE`` or the site's Voxhelm settings, resolved as for
Voxhelm jobs). Without a hint, or with ``auto``, the language of the podcast
page's locale is used, which Wagtail derives from ``LANGUAGE_CODE``. Built-in
common-word lists exist for English and German (``en``, ``de``, also with
region suffixes such as ``de-DE``). For any other language, variants are saved
without the common-word check, the admin shows a warning after saving, and
variants of that podcast will not be replaced automatically; the term is still
used as a correct spelling.

Importing a glossary
~~~~~~~~~~~~~~~~~~~~

A site that already keeps a list can load it for one podcast:

.. code-block:: bash

   python manage.py import_transcript_glossary <podcast-id-or-slug> glossary.json --dry-run
   python manage.py import_transcript_glossary <podcast-id-or-slug> glossary.json

The file is a JSON list of entries:

.. code-block:: json

   [
     {"term": "Gunicorn", "variants": ["Gunacorn", "Gunna Corn"], "notes": "WSGI server"},
     {"term": "Heroku"}
   ]

``variants`` may also be a newline-separated string; ``variants`` and
``notes`` are optional. Entries are matched to existing terms of the podcast
ignoring case and spacing: a match is updated (its spelling, and its variants
and notes where the entry has them), otherwise a term is created. Every entry
is validated like the admin form, including against the entries before it;
invalid or duplicate entries are skipped and reported on stderr with the
reason, and the valid ones are saved in one transaction. The summary line
counts ``created``, ``updated``, ``unchanged`` and ``skipped`` entries, and
the command exits successfully even when entries were skipped. ``--dry-run``
validates and reports without saving. A slug used by several podcasts is
refused; pass the page id instead.

.. _transcript_glossary_corrections:

Applying corrections
~~~~~~~~~~~~~~~~~~~~

Corrections use the glossary of one episode: the variants of the contributors
assigned to it (hidden contributors included, since variants are never
published), the show terms of its podcast, and correct spellings derived from
its title and show notes (link texts and "by <Author>" phrases in the rich
text of ``body``, latest revision, so draft notes count). The podcast's
transcript language picks the common-word list.

- **Automatic replacements**: a contributor variant, or a show-term variant
  that is not a single common word, is replaced wherever it occurs as a whole
  phrase (case-insensitive, possessives kept: "John's" becomes "Jon's").
- **Proposals**: fuzzy matches of contributor names, show terms and
  show-note spellings change nothing until an editor approves them. An
  approved original applies to every occurrence in that transcript, also to
  occurrences found later; a rejected one is no longer proposed. Occurrences
  decided one by one keep their decision: approving a group leaves occurrences
  rejected individually as they are, and rejecting it keeps those approved
  individually.

Editor decisions are stored as such and do not depend on what the current
glossary still finds. A decision on one occurrence (position, original and
replacement) wins over a decision for the original in the whole transcript,
which wins over the glossary; the latest action on an occurrence or original
counts. So an approved occurrence or original stays replaced when its glossary
entry is removed, and a rejected one stays unchanged also when the glossary
later lists it as a variant. Rejected replacements are listed but never
applied. Approved replacements are applied before automatic ones; an automatic
replacement that overlaps an approved one is dropped.

After every Voxhelm import (admin request, queued completion or
``generate_transcripts``), the glossary runs automatically. A failure in this
step is logged on ``cast.voxhelm.service`` and keeps the imported transcript.

The episode is the one the import was requested for (the episode page's
*Generate transcript* action, also when the completion runs in the task
queue, or ``generate_transcripts`` for an episode), or else the only episode
using the audio. When the audio is used by several episodes, nothing is
replaced until an editor picks one of them; the choice is stored. If the
stored episode no longer uses the audio, re-applying changes nothing and the
editor is asked again.

The state lives in a private sidecar, ``Transcript.corrections``
(``cast_transcript_corrections/``, the same protected storage as the
known-speaker sidecar). It holds each Podlove segment's raw text as received,
the replacements with their state (``auto``, ``approved``, ``rejected``), the
proposals and the editor's decisions. It is never served: APIs, feeds, the
player and theme templates read only the Podlove, DOTe and WebVTT files. For a
transcript that has no sidecar yet, the first run takes the current Podlove
text as raw text.

Applying is a function of the raw text and the replacements that are not
rejected: it rewrites the text of the corrected segments in Podlove, DOTe
(``text``) and WebVTT (the cue text; voice tags and ``Speaker N:`` prefixes
are kept), matched by start time, and running it again changes nothing. Only
segment text is changed, so known-speaker application can run before or after
it, and approved speaker mappings stay current (the files' source fingerprint
is kept). A new Voxhelm import or upload starts a fresh sidecar from the new
text; earlier approvals and decisions are not carried over, so add misspellings
that should always be fixed to the glossary.

After editing the glossary, re-apply it:

.. code-block:: bash

   python manage.py apply_transcript_glossary --podcast <podcast-id-or-slug> --dry-run
   python manage.py apply_transcript_glossary --transcript 12 --transcript 13
   python manage.py apply_transcript_glossary --all

.. _transcript_glossary_review:

Reviewing corrections
~~~~~~~~~~~~~~~~~~~~~

The transcript edit view (*Media → Transcripts → Edit*) has a *Glossary
corrections* section next to the known-speaker review. Anyone who may edit the
transcript can use it:

- A summary counts the automatic and approved replacements, the open proposal
  groups and the occurrences left to decide, and names the episode that
  supplies the glossary. *Re-apply glossary* recomputes the corrections with
  the current glossary (as ``apply_transcript_glossary`` does).
- When the audio is used by several episodes, or the stored episode no longer
  uses it, the section asks for the episode instead and applies the glossary
  once one is chosen.
- Proposals are grouped by correct spelling. Each group lists its originals
  with their counts and the first occurrences in context, with the matched
  phrase highlighted. *Approve all* and *Reject all* decide every original of
  the group for the whole transcript; occurrences already decided one by one
  keep their decision. *Approve and add to glossary* approves
  one original and adds it as a variant of the podcast's show term with that
  spelling, else of the credited contributor whose name it is, else of a new
  show term; it is refused with the validation message when the variant is not
  allowed (for example a common word as show-term variant), and it needs the
  permissions to add and change transcript glossary terms and to change
  contributors. *Decide one by one* opens every occurrence with its own
  *Approve* and *Reject*.
- The replacements in effect (automatic and approved) are listed with their
  context and can be rejected one by one; rejected ones stay rejected when the
  glossary is re-applied.
- Rejected occurrences (rejected replacements and rejected proposals) are
  counted in the summary and listed apart, each with *Approve* to undo the
  rejection.

Each occurrence's time stamp plays the audio from the start of its segment to
the start of the next one, when the audio has a playable file.

Common-word lists
~~~~~~~~~~~~~~~~~

The common-word lists in ``cast/transcripts/common_words/`` hold the 10,000
most frequent word forms of the English and German sentence collections of
`Tatoeba <https://tatoeba.org>`_, licensed `CC BY 2.0 FR
<https://tatoeba.org/en/terms_of_use>`_; attribution: Tatoeba and its
contributors. The files contain word forms only, no sentences.
