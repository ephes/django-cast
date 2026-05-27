# Audio Transcript Diarization Mode

## Context

Voxhelm can diarize mastered/mixed audio, but that result is inherently weaker than diarization derived from separate
speaker tracks. For some episodes, especially with more than three speakers, similar voices, crosstalk, or heavy
editing, the generated speaker clusters can be worse than no speaker labels at all.

django-cast currently stores transcript artifacts on `Audio` through `Transcript`, not on individual `Episode`
revisions. One audio file can be reused by multiple episodes, and regenerating a transcript updates the shared
transcript artifacts for every episode using that audio.

The existing site/global Voxhelm diarization setting is too coarse:

- disabling it site-wide prevents diarization for every audio file
- keeping it enabled means a bad diarized transcript can keep showing speaker labels unless the files are re-uploaded
  or rewritten
- changing the setting after a transcript was generated does not rewrite existing Podlove, DOTe, or WebVTT artifacts

This note complements the broader diarization design history in
[Speaker Diarization](2026-05-18-speaker-diarization.md). It does not decide whether django-cast keeps the current
destructive speaker-label rewrite workflow or later adds a non-destructive `TranscriptSpeakerMapping` model. The
audio-level mode below works with the current stored artifacts either way.

## Terms

- **Segmentation**: transcript text split into timestamped segments or cues. django-cast should keep this even when
  speaker diarization is disabled.
- **Diarization**: assigning timestamped speech to speaker clusters or labels.
- **Speaker labels**: stored values such as `Speaker 1`, `Jochen`, Podlove `speaker` / `voice`, DOTe
  `speakerDesignation`, and WebVTT `<v ...>` labels.
- **Contributor mapping**: editor-approved mapping from transcript speaker labels to episode contributors.

## Proposed Behavior

Add a persistent audio-level transcript diarization mode. The mode controls future Voxhelm diarization requests and
gives editors a non-destructive way to suppress bad stored speaker labels in public output.

Suggested field:

```python
Audio.transcript_diarization_mode
```

Suggested values:

- `inherit`: use the site/global Voxhelm diarization setting for future generation. This is the default for existing
  and newly created audio so migrations preserve current behavior.
- `enabled`: request Voxhelm diarization for this audio, regardless of the site/global default. Public output may show
  stored speaker labels if they pass the public contributor sanitizer.
- `disabled`: do not request Voxhelm diarization for this audio. Public output suppresses speaker labels, even if
  existing transcript artifacts still contain them.

This mode should not delete or rewrite stored transcript artifacts by itself.

`inherit` inherits only the generation policy. The existing site/global Voxhelm setting controls whether new Voxhelm
jobs request diarization; it does not currently control public display of speaker labels. Under `inherit`, public
display remains governed by the existing public contributor sanitizer, regardless of whether the site/global
diarization setting is currently true or false.

## State Model

The transcript diarization mode and the current transcript files are related, but they are not the same state. The
table shows public output for the current stored transcript state.

| Transcript diarization mode | Stored transcript labels | Future generation | Public output |
| --- | --- | --- | --- |
| `inherit` | none | inherits site/global diarization | transcript text without speakers |
| `inherit` | present | inherits site/global diarization | labels may show when allowed by public sanitizer |
| `enabled` | none | requests diarization | no speakers until files contain labels |
| `enabled` | present | requests diarization | labels may show when allowed by public sanitizer |
| `disabled` | none | no diarization payload or speaker-count hint | transcript text without speakers |
| `disabled` | present | no diarization payload or speaker-count hint | stored labels hidden from public output |

This avoids destructive side effects:

- changing from `enabled` to `disabled` immediately hides bad speaker labels publicly, but keeps the stored data
  available for inspection, remapping, or later re-enabling
- changing from `disabled` back to `enabled` can show existing labels again if they are still present and public
  sanitizer allows them
- regenerating while `disabled` should normally produce fresh artifacts without service-generated speaker labels

The state “mode is enabled, but transcript files have no speaker labels” is valid. It means future generation should
request speaker labels, while the current transcript simply does not contain any yet.

The state “mode is disabled, but transcript files still have speaker labels” is also valid. It means the labels are
stored private/admin data, but not part of public output.

## Public Output Rules

When the effective transcript diarization mode is `disabled`, public transcript surfaces should behave as if no
speaker labels are allowed:

- Podlove player JSON should omit transcript `speaker` / `voice` fields and top-level transcript contributors.
- Public Podlove transcript JSON should omit disallowed speaker fields.
- PodcastIndex JSON converted from DOTe should emit blank speakers.
- WebVTT output should strip `<v ...>` labels and generic `Speaker N:` prefixes while preserving cue text and timing.
- HTML transcript pages should render transcript text without speaker names.

When the mode is `inherit` or `enabled`, public output should use the existing public sanitizer: only labels matching
visible contributors on the live episode are exposed. In particular, `inherit` does not mean "hide public labels when
the site/global generation setting is false"; the site/global setting is generation-only.

## Generation Rules

For Voxhelm submission:

- `disabled`: send no `diarization` payload and no `speaker_count` / `num_speakers` hint.
- `enabled`: send `{"diarization": {"enabled": true}}`; include the existing speaker-count hint when an episode
  context can provide one.
- `inherit`: behave like the current site/global setting resolution.

The task reference should continue to make diarized jobs distinguishable from non-diarized jobs. A disabled audio
should use the non-diarized task reference variant. An enabled audio should use the diarized task reference variant,
including the optional speaker-count suffix when available.

## Admin UX

The setting belongs on `Audio`, because transcript generation and transcript artifacts are audio-level. Episode edit
pages may expose the setting or link to it, but help text must be clear that changing it affects the shared audio
transcript used by every episode that references the audio.

Suggested help text:

> Controls speaker diarization for transcript generation and public speaker-label display for this audio. Disabling
> keeps transcript text and timestamps, hides any stored speaker labels publicly, and future generations will not
> request speaker diarization.

## Explicit Cleanup

An optional separate admin action can be added later:

- `Clear stored speaker labels`

That action would destructively remove speaker labels from Podlove, DOTe, and WebVTT artifacts while preserving text
and timings. This would be another in-place artifact rewrite path, similar in shape to the current
`Transcript.rewrite_speaker_labels` mapping action, not a regeneration or re-fetch from Voxhelm. It should not be
triggered automatically by changing `Audio.transcript_diarization_mode`.

Keeping cleanup separate makes the normal disable flow reversible and safe for experimentation.

## Relationship To Local Diarization

Local diarization from separate speaker tracks remains a separate import problem. A later importer could write
speaker labels into Podlove, DOTe, and WebVTT based on local speaker-turn metadata. Those labels would still be
governed by this transcript diarization mode:

- `enabled` or `inherit`: locally imported labels can appear publicly if they match visible contributors.
- `disabled`: locally imported labels remain stored but hidden publicly.

## Acceptance Criteria

- An `Audio` can explicitly inherit, enable, or disable transcript speaker diarization/display.
- Existing and newly created audio defaults to `inherit`.
- Audio admin generation, episode admin generation, and `generate_transcripts` all honor the transcript diarization
  mode.
- Disabled mode sends no Voxhelm diarization payload and no speaker-count hint.
- Disabled-mode submissions use the non-diarized task reference variant; enabled-mode submissions use the diarized
  variant with the optional speaker-count suffix.
- Disabled mode suppresses public speaker labels without rewriting stored artifacts.
- Existing public speaker sanitization remains active for inherited/enabled modes.
- Help text explains that transcripts are shared by audio and may affect multiple episodes.
- Tests cover generation payloads, task references, public Podlove player JSON, public Podlove transcript JSON,
  PodcastIndex JSON, WebVTT, and HTML transcript output.
- Documentation and release notes are updated when the feature ships.
