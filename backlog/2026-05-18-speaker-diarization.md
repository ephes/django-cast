# Speaker Diarization

## Context

django-cast can generate transcripts through Voxhelm and stores the returned Podlove JSON, DOTe JSON, and WebVTT
artifacts on `Transcript`.

Voxhelm batch transcription now supports generic speaker diarization by sending this top-level option on
`POST /v1/jobs` with `job_type=transcribe`:

```json
{
  "diarization": {"enabled": true}
}
```

When enabled, Voxhelm emits generic speaker labels:

- verbose JSON segment `speaker`: `Speaker 1`
- DOTe line `speakerDesignation`: `Speaker 1`
- Podlove transcript `speaker` / `voice`: `Speaker 1`
- WebVTT remains unchanged for now.

This was smoke-tested locally against a short `pp_67` clip. The Voxhelm job succeeded and returned `Speaker 1` /
`Speaker 2` labels in JSON, DOTe, and Podlove.

The important modeling distinction: diarization separates voices into clusters, but it does not prove real-world
identity. `Speaker 1` means "the first detected speaker cluster", not "the first configured contributor".

## Decision

Status note: this section documents the originally preferred non-destructive design. The landed `0.2.57` workflow is
different: it rewrites Podlove/DOTe speaker labels in place after editor approval. See [Current State](#current-state)
for shipped behavior and remaining gaps. The open shaping item in `BACKLOG.md` decides whether to keep the destructive
workflow as v1 or implement the non-destructive mapping model described here.

Do not send episode contributors to Voxhelm for the first django-cast diarization implementation.

The originally proposed durable implementation sends only the generic diarization flag, persists the raw Voxhelm
artifacts unchanged, then lets django-cast extract the generic labels and map them to contributor records or one-off
display names in an editor-controlled workflow.

Reasons:

- Voxhelm's current capability is diarization, not reliable speaker identification.
- Contributor order is editorial metadata; diarization label order is determined by first detected speech.
- Names alone do not let a diarization backend identify voices. Automatic assignment from names or role order would
  create plausible but wrong labels.
- django-cast already owns `Contributor` and `EpisodeContributor`; mapping is an editorial concern and should be
  reviewable without rerunning a long transcription job.
- Persisting raw `Speaker N` artifacts keeps the Voxhelm result auditable and makes remapping reversible.

Future Voxhelm speaker hints are still possible, but they should be treated as suggestions, not final identity
assignments, unless Voxhelm adds an explicit speaker-recognition contract with confidence scores and reviewed voice
enrollment.

## Current State

The first usable django-cast diarization path has landed for `0.2.57`:

- Voxhelm jobs can request generic diarization through `CAST_VOXHELM_DIARIZATION_ENABLED` or the site-level Wagtail
  Voxhelm setting.
- Diarized jobs use a distinct `task_ref` suffix so older non-diarized Voxhelm jobs are not reused.
- django-cast still sends no contributor identities to Voxhelm.
- Generated Podlove, DOTe, and WebVTT artifacts are saved from Voxhelm as returned.
- The transcript edit view extracts Podlove/DOTe speaker labels and lets editors map them to episode contributors.
- The current mapping UI rewrites Podlove `speaker`/`voice` and DOTe `speakerDesignation` fields in place, while
  leaving WebVTT unchanged.
- Mapping choices include persisted and draft episode contributor assignments.
- `python-podcast` is pinned to a django-cast `develop` commit with these changes and has deployment notes plus a
  longer `CAST_VOXHELM_POLL_TIMEOUT` for full-episode diarization jobs.
- The Podlove player API (`AudioPodloveSerializer`) returns a top-level `contributors` list derived from non-blank
  transcript `speaker`/`voice` labels, so Podlove Web Player can resolve and render transcript segment speaker names.

Important gaps remain:

- There is no `TranscriptSpeakerMapping` model yet.
- The current mapping workflow is destructive after editor approval; it does not preserve raw `Speaker N` labels for
  later audit/remapping without regenerating or re-uploading artifacts.
- There is no one-off display-name mapping for speakers who should not become contributor snippets.
- Mapping rows are not preserved across transcript regeneration or manual re-upload because no mapping rows exist.

## Options

### Option A: Raw Diarization Plus Editor Mapping

Recommended for a durable, reversible mapping workflow. The current `0.2.57` implementation is a smaller
contributor-only rewrite workflow; see [Current State](#current-state).

1. django-cast requests generic diarization from Voxhelm.
2. Voxhelm returns `Speaker N` labels in Podlove and DOTe.
3. django-cast stores those artifacts unchanged.
4. django-cast extracts unique labels from the transcript:
   - Podlove: `transcripts[].speaker` and, if present, `transcripts[].voice`
   - DOTe: `lines[].speakerDesignation`
5. The Wagtail editor maps each raw label to either:
   - a `Contributor`, usually one already assigned to the episode, or
   - a one-off `display_name` for people who should not become reusable contributor snippets.
6. Public transcript output applies the mapping. Unmapped labels remain as `Speaker N`.

This is the safest path for `python-podcast`: generate the slow raw diarized transcript in the existing queued worker,
then review speaker labels in Wagtail.

### Option B: Send Contributor Names As Voxhelm Hints

Not recommended for the first implementation.

This could become useful later for spelling hints or for a future Voxhelm speaker-identification feature, but it
should not assign identities by itself. If added later, the contract should distinguish:

- `speaker_label`: the raw cluster label, for example `Speaker 1`
- `suggested_display_name`: Voxhelm's guess, if any
- `suggested_external_id`: an opaque caller-provided id, if any
- `confidence`: a numeric confidence score
- `needs_review`: true unless a site explicitly opts into automatic application

django-cast should store any Voxhelm identity result as a pending suggestion. The editor still approves the mapping.

### Option C: Speaker Recognition With Voice Enrollment

Future work only.

Reliable automatic mapping would need voice references or enrollment data for known contributors, plus explicit
consent, storage rules, and a Voxhelm API that can compare diarized clusters against enrolled voices. That is a
different feature from plain diarization and should not block generic speaker labels.

If this becomes active work, model the django-cast side as private contributor voice reference material, not as public
contributor profile data. The reference should be a related object owned by `Contributor`, for example:

```python
class ContributorVoiceReference(models.Model):
    contributor = models.ForeignKey(Contributor, related_name="voice_references", on_delete=models.CASCADE)
    source_audio = models.ForeignKey(Audio, null=True, blank=True, on_delete=models.SET_NULL)
    source_episode = models.ForeignKey(Episode, null=True, blank=True, on_delete=models.SET_NULL)
    clip = models.FileField(blank=True)
    start_seconds = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    end_seconds = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    status = models.CharField(max_length=32, default="pending")
    notes = models.TextField(blank=True)
```

The exact storage fields can change, but the important constraints are:

- voice references are private admin/editor data and must not appear in public contributor APIs, feeds, repository
  exports, or theme context by default
- one contributor can have multiple reference clips
- references can come from any episode, not only the episode being transcribed
- same-episode references are usually strongest because microphone, room, language, vocal effort, and mastering chain
  match the target audio
- cross-episode references are still valid and are likely the practical reusable production model for recurring
  contributors, but they need validation against real podcast material before automatic application is trusted
- clean solo speech is more valuable than long noisy clips; prefer reviewed ranges or uploaded clips over arbitrary
  whole-episode audio
- newly created references should start as pending and require explicit editor review before they are sent to Voxhelm
  for automatic speaker identification
- Voxhelm should own embedding extraction and model-versioned embedding/centroid caching where possible, so
  django-cast does not persist model-specific voiceprint blobs that become stale when Voxhelm changes embedding models
- when Voxhelm changes embedding models, it should re-extract centroids from django-cast's stored references rather
  than requiring django-cast to migrate cached embedding blobs

The django-cast to Voxhelm contract should send contributor ids plus private reference clip URLs/artifacts or source
ranges. Voxhelm should return speaker suggestions with confidence, margin, candidates, and `needs_review` metadata.
django-cast should treat these as mapping suggestions unless the site explicitly opts into conservative automatic
application.

### Option D: Rewrite Files Versus Apply Mapping At Read Time

Prefer a non-destructive read-time mapping layer.

Status note: the current `0.2.57` v1 does not do this; it rewrites Podlove/DOTe files after editor approval. This
option remains the durable mapping design if django-cast decides raw-label preservation and remapping are worth the
extra model/UI complexity.

The current public endpoints already load transcript JSON before returning it, so django-cast can apply a mapping when
serving:

- HTML transcript views rendered from Podlove data, including `episode_transcript`, `html_transcript`, and
  `_render_transcript_html`
- Podlove transcript JSON served by `podlove_transcript_json`
- Podlove player API transcript segments served by `AudioPodloveSerializer.get_transcripts` on
  `cast:api:audio_podlove_detail`
- PodcastIndex JSON converted from DOTe

The raw `podlove` and `dote` files would remain the original Voxhelm output. This avoids losing the raw labels and
keeps remapping cheap.

Materializing mapped artifacts is a possible later optimization if static file consumers need it, but then django-cast
should either keep separate raw files or be able to regenerate mapped files from raw artifacts plus the mapping model.
The first mapping slice can leave WebVTT unchanged.

## Proposed Data Model

This data model is only needed if django-cast chooses the non-destructive mapping path. The current `0.2.57` v1 has no
mapping model and rewrites transcript files after editor approval.

Prefer a normalized mapping model over storing raw JSON on `Transcript`:

```python
class TranscriptSpeakerMapping(models.Model):
    transcript = models.ForeignKey(Transcript, related_name="speaker_mappings", on_delete=models.CASCADE)
    speaker_label = models.CharField(max_length=64)
    contributor = models.ForeignKey(Contributor, null=True, blank=True, on_delete=models.SET_NULL)
    display_name = models.CharField(max_length=128, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "speaker_label"],
                name="unique_transcript_speaker_label",
            ),
        ]
```

Rules:

- `speaker_label` is the stable raw Voxhelm label, for example `Speaker 1`.
- `contributor` is optional.
- `display_name` supports guests or off-mic speakers who should not become reusable contributor records.
- If `contributor` is set, the effective public name is `contributor.display_name`.
- If only `display_name` is set, use that value.
- If neither is set, keep the raw `Speaker N` label.
- Mapping should be attached to `Transcript`, not `EpisodeContributor`, because the raw labels belong to the audio
  transcript. The admin UI can still prefer contributors assigned to the current episode as candidate choices.

A JSON field such as `Transcript.speaker_mapping = {"Speaker 1": "alice"}` would be smaller but weaker for Wagtail
forms, validation, future links, contributor deletion behavior, and per-label review state.

## Editor Workflow

This describes the desired workflow for the non-destructive mapping path, not the current contributor-only rewrite UI.

1. After Voxhelm generation, manual transcript import, or manual transcript re-upload, extract speaker labels from
   Podlove and DOTe.
2. Create missing `TranscriptSpeakerMapping` rows for new labels. Keep existing rows when regenerating if the same raw
   label still appears.
3. Show a "Speakers" section on the transcript edit view or on the episode edit workflow:
   - raw label
   - first timestamp or short example snippets to help identify the voice
   - contributor chooser, with episode contributors shown first when the editor is working in a specific episode
     context
   - optional display name field
4. Saving the mapping updates public transcript output immediately.
5. Public output should never fail because a label is unmapped; it should fall back to the raw label.

Do not automatically map `Speaker 1` to the first episode contributor. A cold open, intro voice, guest speaking first,
or model clustering error can all make that wrong.

Because `Episode.podcast_audio` is a `ForeignKey`, one `Audio` and its `Transcript` can be reused by multiple
episodes. The mapping remains transcript-wide, but contributor candidates in the editor must be context-aware: from an
episode edit page, prefer that episode's contributors; from a transcript or audio edit page, either ask for an episode
context or show contributors grouped across all referencing episodes.

## Implementation Slices

### Slice 1: Generic Diarization Enablement

1. Add `CAST_VOXHELM_DIARIZATION_ENABLED`, default false.
2. Add a site-level `VoxhelmSettings.diarization_enabled` boolean-capable field with an inherit state, for example
   `null=True` / `blank=True` where `None` means "use the global/env setting". A plain `BooleanField(default=False)`
   cannot distinguish "unset" from "explicitly disabled", so it would unintentionally override a global true setting
   for every site.
3. Add a boolean-aware settings helper, for example `get_bool_setting`, that preserves the existing precedence
   order: site setting when explicitly set, then Django setting, then environment variable, then default. The current
   site-setting helper only handles string fields and must not call `.strip()` on booleans.
4. Add `diarization_enabled: bool = False` to `VoxhelmClient`.
5. Make `VoxhelmClient.from_settings()` read the global or site-level setting through the boolean helper.
6. Include `{"diarization": {"enabled": true}}` in `submit_transcription_job()` only when enabled.
7. Verify that generated Podlove/DOTe artifacts with speaker fields are saved unchanged.
8. Document the setting, Voxhelm diarization requirement, and operational expectation that full-episode diarization is
   slow and must use the existing queued/running transcript flow.

Status: landed in `0.2.57`.

### Ready Slice: Podlove Player Speaker Labels

Problem: on staging, `/api/audios/podlove/82/post/140/` can return transcript segments such as:

```json
{
  "speaker": "Dominik",
  "voice": "Dominik",
  "text": "..."
}
```

But the same payload does not include top-level Podlove player `contributors`. Podlove Web Player resolves transcript
speaker ids through top-level contributor objects and renders `speaker.name`; it does not render the raw transcript
`speaker` string directly. The transcript detail view works because Django templates render `{{ segment.speaker }}`
directly.

First implementation:

1. Confirm the Podlove Web Player v5 `contributors` schema and transcript `speaker`/`voice` id resolution against
   player source or official docs before changing the API payload.
2. Add `contributors` to `AudioPodloveSerializer`.
3. Derive first-appearance, deduplicated contributors from non-blank Podlove transcript `speaker` and `voice` values.
   Do not use `Transcript.get_speaker_labels()` directly for this payload: it sorts labels and also includes DOTe
   `speakerDesignation` values.
4. Use the label as both `id` and `name` for the immediate fix if step 1 confirms that this matches the player
   contract, for example `{"id": "Dominik", "name": "Dominik"}`.
5. Keep the existing `transcripts` payload unchanged.
6. Avoid parsing `transcript.podlove` twice per player API request; share one JSON load between transcript and
   contributor extraction.
7. Add tests for contributor extraction, duplicate handling, blank labels, invalid/missing transcript JSON, and the
   existing no-transcript path.
8. Verify on a diarized staging episode that Podlove Web Player displays speaker labels.

Status: landed in `0.2.57`. The Podlove Web Player v5 contributor contract was verified against the player source
(`store/speakers` reads the top-level `contributors`; `effects/transcripts/fetch.js` resolves a segment `speaker`
against contributor `id`; `tabs/transcripts/Entry.vue` renders `contributor.name`). `AudioPodloveSerializer` now emits
the `contributors` payload with `{"id": label, "name": label}` entries, shares a single Podlove JSON load with
`get_transcripts`, and has focused tests. Implementation, automated tests, and docs are complete, so this slice is not
tracked as open work in `BACKLOG.md`. The one follow-up is an operational deploy-time check rather than implementation
work: confirm on a diarized staging episode (for example, the next `python-podcast` diarized deploy) that Podlove Web
Player renders the speaker names end to end.

If the non-destructive mapping model is implemented later, this API can switch from label-derived contributor objects
to mapped contributor/display-name objects while keeping transcript `speaker` ids and top-level contributor ids in
sync.

### Slice 2: Mapping Model And Label Extraction

1. Add `TranscriptSpeakerMapping`.
2. Add helper functions to extract ordered labels from Podlove and DOTe data.
3. Populate missing mapping rows after transcript generation and when opening/saving transcript admin forms.
4. Add tests for label extraction, duplicate handling, blank speaker fields, and preserving existing mappings across
   regeneration or manual re-upload.

Status: label extraction landed as `Transcript.get_speaker_labels()`. The mapping model and persisted mapping rows
remain unbuilt, pending the persistence decision.

### Slice 3: Editor Mapping UI And Public Output

1. Add a Wagtail admin mapping editor.
2. Apply mappings in Podlove JSON, the Podlove player API, HTML transcript views, and DOTe-derived PodcastIndex JSON at
   read time.
3. Keep WebVTT unchanged unless a separate VTT speaker-label design is accepted.
4. Add tests for mapped Podlove output, mapped PodcastIndex output, unmapped fallback behavior, and hidden/deleted
   contributor behavior.

Status: partially landed as a contributor-only Wagtail form that rewrites Podlove/DOTe files in place. Read-time
mapping, one-off display names, and persistent mapping records remain undecided.

## python-podcast Integration Notes

`python-podcast` should treat diarization as a slower queued transcript-generation path:

1. Bump the `django-cast` dependency to a commit containing the diarization setting.
2. Run migrations if `VoxhelmSettings` gains `diarization_enabled` or mapping models.
3. Enable `CAST_VOXHELM_DIARIZATION_ENABLED=true` or use the site-level Wagtail setting.
4. Ensure Voxhelm is configured with its diarization backend and Hugging Face token.
5. Document that full-episode diarization can be CPU-heavy. A short local clip took about 88 seconds; a full
   101-minute episode should not block a Wagtail admin request.
6. After generation, review and map raw speakers in Wagtail before treating contributor names in transcripts as final.

## Open Questions

- Should mapped public output be enabled as soon as any mapping row exists, or only after an explicit "reviewed"
  marker?
- Should the admin UI allow selecting any `Contributor`, or only contributors assigned to the episode plus a
  "display name only" escape hatch?
- If one `Audio` is reused by multiple episodes, should there be a transcript-wide mapping only, or an optional
  episode-specific override?
- On manual transcript re-upload, should mappings for labels that no longer appear be kept as inert history, hidden
  from the editor, or deleted?
- Should a later VTT speaker-label format be generated, and which clients consume it correctly?
- How should overlapping speech, merged clusters, or split clusters be represented in the editor?
- What consent, retention, and access rules should apply to private contributor voice reference clips?
- Should Voxhelm receive signed private clip URLs, copied job artifacts, source ranges into existing private media, or
  precomputed embeddings?
- How well do cross-episode contributor references perform compared with same-episode references for `python-podcast`
  regulars?

## Acceptance Criteria

Status note: these criteria describe the complete durable diarization design. The current `0.2.57` v1 meets the
generic Voxhelm enablement and contributor-controlled rewrite path, but it does not retain raw artifacts after mapping
and does not support one-off display names. Those parts depend on the open mapping persistence decision.

- django-cast can submit Voxhelm transcript jobs with generic diarization enabled by configuration.
- Existing behavior remains unchanged when the setting is false.
- Generated Podlove/DOTe artifacts with generic speaker labels are persisted unchanged.
- Contributor identity is not inferred from episode contributor ordering.
- There is a clear editor-controlled mapping path from raw `Speaker N` labels to contributors or one-off display
  names.
- Public transcript output can show mapped names while retaining raw artifacts for audit and remapping.
- Docs and release notes mention the setting, Voxhelm requirement, and queued-worker operational expectation.
- `python-podcast` has a concrete integration path that does not block Wagtail admin requests on full-episode
  diarization.
