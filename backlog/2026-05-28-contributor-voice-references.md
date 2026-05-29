# Contributor Voice References

## Context

Voxhelm's diarization quality research for the Python Podcast DjangoCon Europe
2025 episode showed that anonymous pyannote diarization is not enough for
known-speaker podcast workflows. django-cast passed the expected speaker count
and Voxhelm stored the diarization request correctly, but pyannote still merged
one real speaker into another cluster and produced a tiny fourth cluster.

The django-cast speaker-mapping UI can rename useful anonymous clusters, but it
cannot recover a contributor when the diarization backend did not create a
separate cluster for that voice.

The same Voxhelm research showed a stronger path: known-speaker embedding
classification using clean contributor reference material classified the
problem episode far better than anonymous diarization. For this workflow,
anonymous diarization should become a fallback/debug signal, while contributor
voice references enable known-speaker suggestions.

Related Voxhelm research: `../../voxhelm/specs/diarization-quality-research.md`.

## Decision

django-cast should model private contributor voice reference material. Treat
"voiceprint" as an implementation concept, not public contributor profile data.
The django-cast side should store reviewed reference clips or source ranges and
the editorial state around them. Voxhelm should own model-specific embedding
extraction, centroid caching, and segment classification.

Reasons:

- Voice embeddings are model-specific. Persisting raw embedding blobs in
  django-cast would create stale data when Voxhelm changes embedding models.
- Contributor voice references are sensitive private editorial data. They must
  not leak through public contributor APIs, feeds, theme context, repository
  exports, or generated static assets.
- Clean solo reference clips can be reused across episodes for recurring
  contributors, but each reference still needs consent/review state and source
  metadata.
- Same-episode references are likely strongest, but cross-episode references are
  the practical production model for recurring hosts and guests.
- Voxhelm should return candidates, confidence/margin metadata, raw diarization
  labels, and uncertainty flags. django-cast should store and review those
  suggestions instead of treating speaker identity as automatically final.

## Proposed Data Model

The first django-cast slice should add storage for private reference material
only. It should not submit references to Voxhelm or change public transcript
output yet.

Sketch:

```python
class ContributorVoiceReference(models.Model):
    contributor = models.ForeignKey(Contributor, related_name="voice_references", on_delete=models.CASCADE)
    title = models.CharField(max_length=128, blank=True)
    source_audio = models.ForeignKey(Audio, null=True, blank=True, on_delete=models.SET_NULL)
    source_episode = models.ForeignKey(Episode, null=True, blank=True, on_delete=models.SET_NULL)
    clip = models.FileField(upload_to="cast_voice_references/", null=True, blank=True)
    start_seconds = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    end_seconds = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    status = models.CharField(max_length=32, default="pending")
    notes = models.TextField(blank=True)
```

Field names can change during implementation. Keep these rules:

- A reference should be either an uploaded/managed clip or a source range into
  existing audio, not an ambiguous mixture.
- Source ranges need `start_seconds < end_seconds`.
- Approved references must contain clean solo speech from the contributor.
- New references start as `pending` and must be explicitly approved before they
  can be sent to Voxhelm.
- Disabling or hiding a public contributor must not delete reference material,
  but hidden contributors should not be sent as known-speaker references for
  public transcript generation unless an editor explicitly approves that use.
- Reference files must use private/protected storage or private source ranges.
  Do not put voice-reference clips into public media storage unless access is
  protected.
- References are admin/editor data only. Exclude them from public APIs, feeds,
  repository serialization, theme context, and default contributor exports.

Possible statuses:

- `pending`: captured but not approved for Voxhelm use
- `approved`: can be sent as known-speaker reference material
- `disabled`: retained but not used
- `rejected`: retained for audit/history, not used

## Voxhelm Contract Direction

After the data model exists, django-cast can submit approved references for the
contributors expected on a transcript-generation request. The contract should
send contributor ids plus private reference clip artifacts or source ranges, not
public profile URLs.

Voxhelm-side shape, based on the research note:

```json
{
  "diarization": {
    "enabled": true,
    "strategy": "pyannote_known_speaker",
    "known_speakers": [
      {
        "id": "contributor-id",
        "name": "Johannes",
        "references": [
          {"kind": "clip_artifact", "artifact": "artifact-id-or-url"},
          {"kind": "source_range", "audio_artifact": "artifact-id-or-url", "start": 123.45, "end": 153.45}
        ]
      }
    ],
    "known_speaker": {
      "embedding_model": "pyannote/wespeaker-voxceleb-resnet34-LM",
      "min_segment_duration": 1.5,
      "auto_accept_margin": 0.15,
      "min_top_similarity": 0.55
    }
  }
}
```

Voxhelm should return reviewable speaker metadata, for example:

```json
{
  "speaker": "Johannes",
  "speaker_source": "known_speaker_voiceprint",
  "speaker_confidence": 0.81,
  "speaker_margin": 0.33,
  "speaker_candidates": [
    {"speaker": "Johannes", "similarity": 0.81},
    {"speaker": "Dominik", "similarity": 0.47}
  ],
  "speaker_uncertain": false,
  "raw_diarization_speaker": "SPEAKER_02"
}
```

django-cast should keep uncertainty visible in the admin. Short or low-margin
segments should require editor review instead of being silently accepted.

## Implementation Slices

### Slice 1: Private Voice Reference Storage

1. Add `ContributorVoiceReference`.
2. Add Wagtail admin editing under contributor snippets.
3. Validate clip/source-range shape and status transitions.
4. Ensure references are not serialized into public contributor output, feeds,
   repository exports, theme context, or APIs.
5. Document privacy/storage expectations.
6. Add tests for model validation, admin visibility, and public-output
   non-exposure.

### Slice 2: Voxhelm Known-Speaker Request Contract

1. Add a Voxhelm request shape for known-speaker references after Voxhelm
   supports the contract.
2. Include only approved references for expected episode contributors.
3. Prefer private job artifacts or signed private URLs over public media URLs.
4. Keep anonymous diarization as fallback/debug metadata.
5. Add tests for request payloads, hidden/disabled contributors, missing
   references, and disabled diarization mode.

### Slice 3: Reviewable Speaker Suggestions

1. Store Voxhelm-returned candidates, confidence, margin, uncertainty, source,
   and raw diarization labels.
2. Add an admin review UI for uncertain segments and low-confidence ranges.
3. Apply approved suggestions through the same mapping layer used for public
   transcript output.
4. Avoid destructive artifact rewrites for suggestions; preserve raw metadata
   for audit and remapping.

### Slice 4: Conservative Auto-Accept

Only after real podcast validation, add optional site/audio-level policy for
auto-accepting high-confidence suggestions. Start conservatively, for example
duration `>=1.5s`, margin `>=0.15`, and top similarity around `0.55-0.60`.

## Open Questions

- Should django-cast store uploaded clips, source ranges into existing audio, or
  both in the first slice?
- What private storage backend should be used for uploaded reference clips?
- How should an editor create a clean reference from an existing transcript
  segment or audio range?
- Should approval be a simple status field, or do we need explicit consent and
  reviewer metadata?
- How should references behave when contributors are merged, hidden, or deleted?
- Should the first Voxhelm contract use private signed URLs, copied job
  artifacts, or source ranges into already uploaded audio?
- How should django-cast represent conflicting candidates across regenerated
  transcript artifacts?
- What minimum validation on cross-episode references is enough before enabling
  known-speaker submission for production?

## Success Criteria

- Contributor voice references are private, reviewable, and source-attributed.
- No voice-reference data appears in public contributor/profile/feed/API/theme
  output by default.
- django-cast can select approved references for expected episode contributors.
- Voxhelm can later compute model-versioned embeddings from those references
  without django-cast storing embedding blobs.
- Returned speaker identity remains reviewable and confidence-aware rather than
  silently final.
