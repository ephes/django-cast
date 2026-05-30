# Speaker Diarization

## Context

django-cast can generate transcripts through Voxhelm and stores the returned Podlove JSON, DOTe JSON, and WebVTT
artifacts on `Transcript`.

Voxhelm batch transcription now supports generic speaker diarization by sending this top-level option on
`POST /v1/jobs` with `job_type=transcribe`:

```json
{
  "diarization": {"enabled": true, "num_speakers": 4}
}
```

The `num_speakers` value is optional. django-cast includes it when an episode context provides an expected speaker
count from contributor assignments; otherwise it sends only `{"enabled": true}` for generic diarization.

When enabled, Voxhelm emits generic speaker labels:

- verbose JSON segment `speaker`: `Speaker 1`
- DOTe line `speakerDesignation`: `Speaker 1`
- Podlove transcript `speaker` / `voice`: `Speaker 1`
- WebVTT voice labels such as `<v Speaker 1>...` may appear when the returned VTT carries speaker spans.

This was smoke-tested locally against a short `pp_67` clip. The Voxhelm job succeeded and returned `Speaker 1` /
`Speaker 2` labels in JSON, DOTe, and Podlove.

The important modeling distinction: diarization separates voices into clusters, but it does not prove real-world
identity. `Speaker 1` means "the first detected speaker cluster", not "the first configured contributor".

## Quality Update, 2026-05-28

Voxhelm's follow-up research on a representative four-speaker Python Podcast episode showed that generic pyannote
diarization is not reliable enough to be the primary production path for known-speaker podcasts. django-cast passed
`diarization.num_speakers = 4`, Voxhelm stored that metadata correctly, pyannote returned four labels, and Voxhelm
aligned the turns to transcript segments. The failure was acoustic clustering quality: one real speaker was merged
into another cluster, while the fourth label contained only a tiny number of segments.

That means django-cast's current speaker-mapping UI can only rename bad clusters; it cannot recover a contributor
when Voxhelm never produced a useful cluster for that voice. Anonymous diarization should therefore be treated as a
fallback/debug signal for this workflow, not as sufficient contributor identification.

Known-speaker voice-reference experiments in Voxhelm were much stronger: contributor reference material classified
production mono transcript segments with about 95% accuracy over all segments and 99%+ on segments long enough for a
stable embedding. See `../../voxhelm/specs/diarization-quality-research.md` for the detailed results and recommended
Voxhelm-side postprocessor.

The django-cast side of that direction is tracked separately in
[Contributor Voice References](2026-05-28-contributor-voice-references.md).

## Decision

Decision recorded 2026-05-30: manual anonymous-diarization mapping uses persistent mapping rows applied at read time.
The `0.2.57` manual mapping flow destructively rewrote Podlove/DOTe/WebVTT files in place; the `0.2.58` durable
mapping path replaces that for anonymous manual mappings. The known-speaker path shipped in `0.2.58` is not reopened:
Voxhelm suggestions and editor decisions stay in the private `Transcript.speakers` sidecar, and approved known-speaker
names are applied to public artifacts by the existing review actions.

For the manual `Speaker N` to identity path:

- Store raw Voxhelm or uploaded transcript artifacts as the audit source. Raw `Speaker N` labels are preserved in the
  stored Podlove, DOTe, and WebVTT artifacts by the durable manual mapping path.
- Add a `TranscriptSpeakerMapping` persistent record keyed by transcript and raw `speaker_label`.
- Resolve each raw label to either a `Contributor` or a one-off `display_name`. Contributor mappings use the current
  contributor display name at render time; one-off names cover speakers who should not become reusable contributor
  snippets.
- Apply approved mappings when serving public transcript formats, before the existing public sanitization layer.
  Sanitization remains the final public-leak guard and must allow only approved contributor labels and approved
  one-off mapping names for the live episode/transcript context.
- Preserve mapping rows across transcript regeneration or manual re-upload, but do not assume anonymous cluster labels
  remain identity-stable. When artifacts are replaced, matching raw-label rows stay available for editor review and
  are marked stale or needing review unless the implementation can prove the same raw artifact fingerprint still
  applies. Labels that disappear become inactive history; new labels get new unmapped rows.
- Materialized mapped artifacts are a later optimization only. If added for consumers that bypass django-cast views,
  they must be generated from raw artifacts plus mapping state, never by discarding the raw originals.

Reasons:

- Voxhelm generic diarization separates acoustic clusters; it does not prove real-world identity.
- Contributor order is editorial metadata; diarization label order is determined by first detected speech.
- Anonymous cluster labels are not durable identity keys across regenerated audio, changed diarization settings, or
  manual re-uploads, so old approvals need review when the artifact changes.
- django-cast already owns `Contributor` and `EpisodeContributor`; mapping is an editorial decision and should be
  reviewable without rerunning a long transcription job.
- The existing public transcript sanitizer is the right final safety layer: it already strips labels that are not
  public for the live episode context and can compose with an approved mapping source.
- The private known-speaker sidecar establishes the parallel pattern for preserving raw machine state while applying
  only editor-approved names to public output.

## Current State

The first usable django-cast diarization path landed for `0.2.57`, and the known-speaker recognition path landed for
`0.2.58`:

- Voxhelm jobs can request generic diarization through `CAST_VOXHELM_DIARIZATION_ENABLED` or the site-level Wagtail
  Voxhelm setting.
- Diarized jobs use a distinct `task_ref` suffix so older non-diarized Voxhelm jobs are not reused.
- Generic diarization sends no contributor identities to Voxhelm; the known-speaker path sends only approved private
  voice references (source ranges or uploaded clips), never names or public profile URLs.
- Generated Podlove, DOTe, and WebVTT artifacts are saved from Voxhelm as returned.
- The transcript edit view extracts Podlove/DOTe speaker labels and lets editors map them to episode contributors.
- The manual mapping UI rewrites Podlove `speaker`/`voice`, DOTe `speakerDesignation`, and matching WebVTT voice
  labels in place.
- Mapping choices include persisted and draft episode contributor assignments.
- Per-audio transcript diarization mode (`inherit`/`enabled`/`disabled`) controls future Voxhelm jobs and hides
  stored speaker labels from public output without rewriting files.
- Public transcript surfaces sanitize speaker metadata against live episode contributors, so draft-only names and
  unmapped `Speaker N` labels are hidden until the matching contributor assignment is published.
- Contributors can store private, admin-only `ContributorVoiceReference` material (reviewed clean-solo clips or
  source ranges into existing audio) as known-speaker reference data, consent-gated before approval.
- When known-speaker recognition is enabled, Voxhelm-returned per-segment suggestions (candidates, confidence,
  margin, uncertainty, raw diarization label) are stored as a private `Transcript.speakers` sidecar in protected
  storage and are never exposed publicly.
- The transcript edit view shows a known-speaker review panel; "Approve and apply confident suggestions" writes the
  resolved names into public Podlove, DOTe, and WebVTT output (matched by start time), with optional neighbor
  smoothing for uncertain segments, while preserving the raw sidecar for audit and re-application.
- The known-speaker review panel also supports per-segment approve, reject-to-blank, and correction decisions.
  Decisions are stored additively as `editor_decision` metadata inside the private `Transcript.speakers` sidecar,
  take precedence over the confident/smoothed bulk result, and apply to matching Podlove, DOTe, and WebVTT entries by
  start time.
- The transcript edit view also offers a voice-reference candidate picker that proposes clean solo source ranges
  (split across large untranscribed gaps) for creating pending or consent-gated approved references.
- `python-podcast` is pinned to a django-cast `develop` commit with these changes and has deployment notes plus a
  longer `CAST_VOXHELM_POLL_TIMEOUT` for full-episode diarization jobs.
- The Podlove player API (`AudioPodloveSerializer`) returns a top-level `contributors` list derived from non-blank
  transcript `speaker`/`voice` labels, so Podlove Web Player can resolve and render transcript segment speaker names.

The durable manual mapping path has now landed for `0.2.58`:

- `TranscriptSpeakerMapping` rows preserve raw labels, mapping targets, review state, artifact fingerprints, and
  inactive history.
- Manual anonymous speaker mapping saves mapping rows only; stored Podlove, DOTe, and WebVTT artifacts remain unchanged.
- Mappings can target visible episode contributors or approved one-off display names. One-off display names cannot
  duplicate current raw transcript speaker labels.
- Public transcript responses apply approved current mappings at read time before sanitization across HTML transcripts,
  Podlove JSON, the Podlove player API, DOTe-derived PodcastIndex JSON, and WebVTT responses.
- Regeneration or re-upload preserves rows, marks changed approvals stale, keeps disappeared labels inactive, and
  creates unmapped rows for new labels.

Important gaps remain:

- Anonymous diarization can merge real speakers in production podcast audio; mapping cannot fix a missing cluster.

## Options

### Option A: Raw Diarization Plus Editor Mapping

Useful for well-separated anonymous clusters, but not sufficient as the primary production strategy for recurring
known-speaker podcasts. The current `0.2.57` implementation is a smaller contributor-only rewrite workflow; see
[Current State](#current-state). The durable decision keeps this workflow as the anonymous-diarization fallback, but
stores editor mappings separately and applies them at read time instead of rewriting raw transcript artifacts.

1. django-cast requests generic diarization from Voxhelm.
2. Voxhelm returns `Speaker N` labels in Podlove and DOTe.
3. django-cast stores those artifacts unchanged.
4. django-cast extracts unique labels from the transcript:
   - Podlove: `transcripts[].speaker` and, if present, `transcripts[].voice`
   - DOTe: `lines[].speakerDesignation`
5. The Wagtail editor maps each raw label to either:
   - a `Contributor`, usually one already assigned to the episode, or
   - a one-off `display_name` for people who should not become reusable contributor snippets.
6. Public transcript output applies approved mappings before sanitization. Unmapped, stale, draft-only, or otherwise
   disallowed labels remain available in private/admin state but are hidden by the public sanitizer unless explicitly
   allowed for the live episode/transcript context.

This remains valuable when Voxhelm produces useful clusters, but the Python Podcast quality research shows that a
manual label-mapping workflow cannot recover a voice that was merged into another cluster. For known recurring
contributors, combine this with private voice references and reviewable known-speaker suggestions.

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

Preferred next direction for known-speaker podcast workflows.

Reliable mapping for recurring known speakers needs voice references or enrollment data for contributors, plus
explicit consent/review state, storage rules, and a Voxhelm API that can compare transcript segment audio against
enrolled voices. This is a different feature from plain diarization. Anonymous diarization remains useful as fallback
or debug metadata, but should not be the only source of speaker identity for known-speaker podcasts.

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
ranges. Voxhelm should return speaker suggestions with confidence, margin, candidates, raw diarization labels, and
uncertainty metadata. django-cast should treat these as reviewable mapping suggestions unless the site explicitly
opts into conservative automatic application.

### Option D: Rewrite Files Versus Apply Mapping At Read Time

Decision: use a non-destructive read-time mapping layer for manual anonymous-diarization mappings.

Status note: the `0.2.57` v1 did not do this; it rewrote Podlove/DOTe/WebVTT files after editor approval. The durable
`0.2.58` path replaces that flow with mapping rows and read-time application.

The current public endpoints already load transcript content before returning it, so django-cast can apply a mapping
when serving:

- HTML transcript views rendered from Podlove data, including `episode_transcript`, `html_transcript`, and
  `_render_transcript_html`
- Podlove transcript JSON served by `podlove_transcript_json`
- Podlove player API transcript segments served by `AudioPodloveSerializer.get_transcripts` on
  `cast:api:audio_podlove_detail`
- PodcastIndex JSON converted from DOTe
- WebVTT text served by `webvtt_transcript`

The raw `podlove`, `dote`, and `vtt` files remain the original Voxhelm output. This avoids losing the raw labels and
keeps remapping cheap.

The mapping must run before public sanitization. Sanitization remains the last gate and strips any mapped or raw label
that is not approved for the current live episode/transcript context. One-off display names therefore require the
sanitizer's allowed-label source to include approved mapping rows, not just live `EpisodeContributor` display names.

Materializing mapped artifacts is a possible later optimization if static file consumers need it, but then django-cast
must keep separate raw files or be able to regenerate mapped files from raw artifacts plus the mapping model. The
durable layer applies the same read-time mapping to VTT responses.

## Proposed Data Model

Use a normalized mapping model for manual anonymous-diarization mappings. Do not store the mapping as ad hoc JSON on
`Transcript`: Wagtail forms, contributor deletion behavior, stale-state tracking, and future review metadata all need
model-level validation.

```python
class TranscriptSpeakerMapping(models.Model):
    transcript = models.ForeignKey(Transcript, related_name="speaker_mappings", on_delete=models.CASCADE)
    speaker_label = models.CharField(max_length=64)
    contributor = models.ForeignKey(Contributor, null=True, blank=True, on_delete=models.SET_NULL)
    display_name = models.CharField(max_length=128, blank=True)
    review_state = models.CharField(max_length=32, default="unmapped")
    source_artifact_fingerprint = models.CharField(max_length=128, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "speaker_label"],
                name="unique_transcript_speaker_label",
            ),
        ]
```

Rules:

- `speaker_label` is the raw label in the current transcript artifact, for example `Speaker 1`.
- The unique constraint is per transcript and raw label.
- `contributor` is optional and uses `SET_NULL` so deleting or hiding a contributor does not delete the audit row.
- `display_name` supports guests or off-mic speakers who should not become reusable contributor records.
- If `contributor` is set, the effective public name is `contributor.display_name`.
- If only `display_name` is set, use that value.
- If neither is set, keep the raw `Speaker N` label.
- `review_state` should distinguish at least unmapped, approved, and stale/needs-review states. Only approved rows are
  candidates for public read-time mapping.
- `source_artifact_fingerprint` is a suggested implementation detail for deciding whether an approval still applies to
  the current transcript artifacts. If the raw artifacts are replaced and the fingerprint no longer matches, preserve
  the row but mark it stale or needing review.
- Labels that no longer appear in the current artifacts should remain as inactive history instead of being silently
  deleted. The editor can hide inactive rows by default.
- Mapping should be attached to `Transcript`, not `EpisodeContributor`, because the raw labels belong to the audio
  transcript. The admin UI can still prefer contributors assigned to the current episode as candidate choices.
- Existing transcripts that were already destructively rewritten cannot recover their original `Speaker N` labels from
  django-cast state. A migration must not guess those labels; future durability starts once raw artifacts and mapping
  rows exist.

Validation should enforce that an approved mapping has exactly one target: either `contributor` or `display_name`.
Unmapped or stale rows may have no target, and stale rows may retain their previous target for editor review without
publishing it.

## Editor Workflow

This describes the target workflow for the durable mapping path, not the current contributor-only rewrite UI.

1. After Voxhelm generation, manual transcript import, or manual transcript re-upload, extract speaker labels from
   Podlove and DOTe.
2. Create missing `TranscriptSpeakerMapping` rows for new labels. Keep existing rows when regenerating or re-uploading
   if the same raw label still appears, but mark approved rows stale or needing review when the underlying artifacts
   have changed.
3. Show a "Speakers" section on the transcript edit view or on the episode edit workflow:
   - raw label
   - current review state
   - first timestamp or short example snippets to help identify the voice
   - contributor chooser, with episode contributors shown first when the editor is working in a specific episode
     context
   - optional display name field
4. Saving the mapping updates mapping rows only. It must not rewrite Podlove, DOTe, or WebVTT artifacts.
5. Approved mappings update public transcript output immediately through read-time mapping, then pass through public
   sanitization.
6. Public output should never fail because a label is unmapped or stale. It should fall back to the raw label before
   sanitization; public sanitization then hides labels that are not allowed for the current live context.

Do not automatically map `Speaker 1` to the first episode contributor. A cold open, intro voice, guest speaking first,
or model clustering error can all make that wrong.

Because `Episode.podcast_audio` is a `ForeignKey`, one `Audio` and its `Transcript` can be reused by multiple
episodes. The mapping remains transcript-wide, but contributor candidates in the editor must be context-aware: from an
episode edit page, prefer that episode's contributors; from a transcript or audio edit page, either ask for an episode
context or show contributors grouped across all referencing episodes.

## Implementation Slices

### Ready Slice: Private Contributor Voice References

Add private django-cast storage for reviewed contributor voice reference clips or source ranges. This is tracked in
[Contributor Voice References](2026-05-28-contributor-voice-references.md).

Status: landed in `0.2.58`. The private, admin-only `ContributorVoiceReference` model (reviewed clean-solo clips or
source ranges, consent-gated before approval, excluded from all public surfaces) shipped, establishing the privacy
boundaries the known-speaker recognition follow-ups build on. This first slice did not submit references to Voxhelm or
change public transcript output.

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
6. Include `{"diarization": {"enabled": true}}` in `submit_transcription_job()` only when enabled; include
   `num_speakers` when an episode context provides an expected speaker count.
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

The durable mapping model switches this API from label-derived contributor objects to mapped contributor/display-name
objects while keeping transcript `speaker` ids and top-level contributor ids in sync.

### Slice: Persistent Anonymous Speaker Mapping State

Previously tracked in `BACKLOG.md` as "Persist anonymous transcript speaker mappings".

1. Add `TranscriptSpeakerMapping` or an equivalent normalized model keyed by transcript and raw speaker label.
2. Reuse the landed `Transcript.get_speaker_labels()` helper for extraction; add any ordering or sample helpers needed
   by the editor without changing public output.
3. Populate missing rows after transcript generation, manual transcript upload, and transcript admin open/save.
4. Preserve rows across regeneration and manual re-upload. Matching labels stay attached but become stale or
   needs-review when artifacts change; missing labels become inactive history; new labels become unmapped rows.
5. Do not rewrite stored Podlove, DOTe, or WebVTT artifacts in this slice.
6. Add tests for row creation, duplicate labels, blank fields, uniqueness, contributor deletion or hiding, stale/inactive
   behavior on artifact replacement, and public non-exposure of mapping state.

Status: landed in `0.2.58`. `TranscriptSpeakerMapping` stores transcript-scoped raw labels, contributor or one-off
display-name targets, review state, artifact fingerprints, active/inactive history, and reviewed/last-seen timestamps.
`Transcript.sync_speaker_mappings()` creates rows from Podlove, DOTe, and WebVTT labels, marks approvals stale when
artifacts change, keeps disappeared labels as inactive history, and creates unmapped rows for new labels.

### Slice: Read-Time Speaker Mapping Output And Editor UX

Previously tracked in `BACKLOG.md` as "Apply transcript speaker mappings at read time".

1. Replace the manual contributor-only rewrite action with an editor workflow that saves mapping rows.
2. Support contributor mappings and one-off display-name mappings.
3. Apply approved mappings to Podlove JSON, the Podlove player API `transcripts` and top-level `contributors`, HTML
   transcript views, DOTe-derived PodcastIndex JSON, and WebVTT responses at read time.
4. Run mapping before the existing public sanitization layer. Extend the allowed-label source deliberately so approved
   one-off mapping names can appear publicly while draft, stale, hidden-contributor, and unmapped labels remain hidden.
5. Keep stored Podlove, DOTe, and WebVTT files unchanged. If materialized mapped artifacts are ever needed later, build
   them from raw artifacts plus mapping rows.
6. Add tests for every public transcript format, unmapped and stale fallback behavior, one-off display names,
   hidden/deleted contributors, draft-only assignments, disabled diarization mode, and unchanged raw artifacts.

Status: landed in `0.2.58`. The transcript edit view saves durable mapping rows instead of rewriting artifacts,
supports contributor and one-off display-name targets, and applies approved current mappings before public sanitization
for Podlove JSON, Podlove player API transcripts and contributors, HTML transcripts, DOTe-derived PodcastIndex JSON,
and WebVTT responses.

### Slice 4: Known-Speaker Suggestions From Voxhelm

Depends on private contributor voice references and a Voxhelm known-speaker request/response contract.
The detailed downstream sequencing lives in
[Contributor Voice References](2026-05-28-contributor-voice-references.md); keep this section as the high-level
speaker-state integration summary.

1. Send approved reference material for expected episode contributors when the transcript generation request opts into
   known-speaker recognition.
2. Store Voxhelm-returned candidates, confidence, margin, raw diarization labels, and uncertainty flags as transcript
   speaker state.
3. Show uncertain or low-margin segments in the admin review workflow.
4. Apply approved speaker identity to public transcript output while preserving raw private suggestion metadata.
5. Preserve raw Voxhelm metadata for audit and remapping.

Status: landed in `0.2.58`. Diarized jobs that opt into known-speaker recognition send approved reference material for
expected contributors, and Voxhelm-returned candidates/confidence/margin/raw labels/uncertainty are stored as the
private `Transcript.speakers` sidecar and preserved for audit and re-application. The Wagtail transcript edit view
shows the known-speaker review panel, supports per-segment approve/reject/correct decisions for uncertain or
low-margin segments, stores those decisions additively in the sidecar, and applies the resolved names or blanks to
public Podlove, DOTe, and WebVTT output by start time. Voxhelm research still recommends classifying transcript
segments directly from the mastered mono audio and using diarization turns as smoothing/fallback rather than the
primary unit for known-speaker recovery.

## python-podcast Integration Notes

`python-podcast` should treat diarization as a slower queued transcript-generation path:

1. Bump the `django-cast` dependency to a commit containing the diarization setting.
2. Run migrations if `VoxhelmSettings` gains `diarization_enabled` or mapping models.
3. Enable `CAST_VOXHELM_DIARIZATION_ENABLED=true` or use the site-level Wagtail setting.
4. Ensure Voxhelm is configured with its diarization backend and Hugging Face token.
5. Document that full-episode diarization can be CPU-heavy. A short local clip took about 88 seconds; a full
   101-minute episode should not block a Wagtail admin request.
6. After generation, review and map raw speakers in Wagtail before treating contributor names in transcripts as final.
7. For recurring known speakers, prefer approved contributor voice references and the known-speaker review path;
   anonymous diarization alone is not sufficient on merged-cluster episodes.

## Open Questions

- Should the first mapping editor allow selecting any `Contributor`, or only contributors assigned to the episode plus
  a one-off display-name escape hatch?
- Should a later implementation add episode-specific mapping overrides on top of the transcript-wide mapping when one
  `Audio` is reused by multiple episodes?
- What exact artifact fingerprint or revision token is enough to keep an approved mapping active after a save, and when
  should replacement artifacts always force stale/needs-review state?
- Should a later VTT speaker-label format be generated, and which clients consume it correctly?
- How should overlapping speech, merged clusters, or split clusters be represented in the editor?
- Should materialized mapped artifacts ever be added for clients that bypass django-cast public transcript views?

## Acceptance Criteria

These criteria describe the complete durable diarization design. The `0.2.58` durable manual mapping and known-speaker
sidecar paths keep raw machine state private or unchanged while applying only reviewed public labels.

- django-cast can submit Voxhelm transcript jobs with generic diarization enabled by configuration.
- Existing behavior remains unchanged when the setting is false.
- Generated or uploaded Podlove/DOTe/WebVTT artifacts with generic speaker labels are persisted unchanged by the
  durable manual mapping path.
- Contributor identity is not inferred from episode contributor ordering.
- `TranscriptSpeakerMapping` or equivalent rows preserve raw labels, mapping targets, and review/stale state across
  transcript regeneration and manual re-upload.
- There is a clear editor-controlled mapping path from raw `Speaker N` labels to contributors or approved one-off
  display names.
- Public transcript output can show approved mapped names while retaining raw artifacts for audit and remapping.
- Read-time mapping covers HTML transcripts, Podlove JSON, the Podlove player API, DOTe-derived PodcastIndex JSON, and
  WebVTT responses.
- Public sanitization runs after mapping and hides draft-only, hidden-contributor, stale, unmapped, or otherwise
  unapproved labels. Approved one-off display names are explicitly allowed only for the live transcript/episode context.
- Known-speaker workflows keep private contributor voice references and `Transcript.speakers` suggestion metadata out of
  public output.
- Docs and release notes mention user-facing settings or workflow changes in the implementation slices that ship them.
- `python-podcast` has a concrete integration path that does not block Wagtail admin requests on full-episode
  diarization.
