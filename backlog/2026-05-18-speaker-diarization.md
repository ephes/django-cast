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

Do not send episode contributors to Voxhelm for the first django-cast diarization implementation.

The first implementation should send only the generic diarization flag, persist the raw Voxhelm artifacts unchanged,
then let django-cast extract the generic labels and map them to contributor records or one-off display names in an
editor-controlled workflow.

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

## Options

### Option A: Raw Diarization Plus Editor Mapping

Recommended.

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

### Option D: Rewrite Files Versus Apply Mapping At Read Time

Prefer a non-destructive read-time mapping layer.

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

### Slice 2: Mapping Model And Label Extraction

1. Add `TranscriptSpeakerMapping`.
2. Add helper functions to extract ordered labels from Podlove and DOTe data.
3. Populate missing mapping rows after transcript generation and when opening/saving transcript admin forms.
4. Add tests for label extraction, duplicate handling, blank speaker fields, and preserving existing mappings across
   regeneration or manual re-upload.

### Slice 3: Editor Mapping UI And Public Output

1. Add a Wagtail admin mapping editor.
2. Apply mappings in Podlove JSON, the Podlove player API, HTML transcript views, and DOTe-derived PodcastIndex JSON at
   read time.
3. Keep WebVTT unchanged unless a separate VTT speaker-label design is accepted.
4. Add tests for mapped Podlove output, mapped PodcastIndex output, unmapped fallback behavior, and hidden/deleted
   contributor behavior.

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

## Acceptance Criteria

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
