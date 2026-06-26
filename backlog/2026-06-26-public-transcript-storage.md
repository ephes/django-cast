# Public Transcript Storage Alias

Date: 2026-06-26

Status: Historical rationale for the implemented `cast_public_transcripts`
storage split. See the linked analysis for rationale, options, and migration
details:
[2026-06-26-public-transcript-storage-analysis.md](2026-06-26-public-transcript-storage-analysis.md).

## Problem

`Transcript.podlove`, `Transcript.vtt`, and `Transcript.dote` are public
transcript artifacts: feeds, public transcript pages, and the custom player all
serve their content to anonymous listeners. Today those fields use
`get_private_media_storage()`, which resolves through the `cast_private_media`
storage alias.

That alias name and behavior are wrong for these artifacts. It conflates public
transcript output with genuinely private media such as known-speaker sidecars
and contributor voice references.

`python-podcast` currently works around this by configuring `cast_private_media`
to point at the same public S3 bucket as normal media. This restores public
transcript reads, but it is a confusing and fragile deployment shape.

## Goal

Split transcript artifact storage from private media storage:

- public transcript artifacts:
  - `Transcript.podlove`
  - `Transcript.vtt`
  - `Transcript.dote`
- private editorial/voice artifacts:
  - `Transcript.speakers`
  - `ContributorVoiceReference.clip`
  - source ranges and sidecar metadata

## Proposed Implementation

Add a dedicated storage alias for public transcript artifacts, for example:

```python
STORAGES = {
    "cast_public_transcripts": {"BACKEND": "..."},
    "cast_private_media": {"BACKEND": "..."},
    "cast_voice_references": {"BACKEND": "..."},
}
```

The exact alias name can change during implementation, but it should communicate
that Podlove, WebVTT, and DOTe files are publishable transcript output, not
private processing data.

Use the new alias for:

- `Transcript.podlove`
- `Transcript.vtt`
- `Transcript.dote`

Keep the private alias/storage path for:

- known-speaker suggestion sidecars (`Transcript.speakers`)
- contributor voice references
- any future non-public Voxhelm raw artifacts

## Backward Compatibility

The new transcript storage helper should preserve existing deployments:

1. If the new transcript storage alias is configured, use it.
2. Otherwise fall back to an explicitly configured `cast_private_media` alias
   for deployments that already adopted the temporary behavior.
3. If neither alias is configured, fall back to Django's default storage,
   preserving the original public-media behavior.

This lets existing installations upgrade without immediate settings changes,
while giving sites with public transcripts a clear way to configure the intended
storage.

## Implementation Notes

- Add a new helper near `cast.private_storage`, e.g.
  `get_transcript_storage()`.
- Update transcript file fields to use that helper for Podlove, WebVTT, and
  DOTe.
- Keep `get_private_media_storage()` for actual private artifacts only.
- Update docs for transcript storage, Voxhelm generation, and known-speaker
  sidecars.
- Add release notes describing the new alias and the compatibility fallback.
- Check consumer settings in `../python-podcast` after implementation.

## Tests

Add focused tests that prove:

- Podlove/VTT/DOTe fields use the transcript storage helper.
- `Transcript.speakers` still uses private/voice-reference storage.
- the helper falls back to explicit `cast_private_media` when the new alias is
  absent, and to default storage when both aliases are absent.
- transcript reads, writes, safe replacement, speaker-label rewrites, and
  Voxhelm artifact saves still operate through the expected storage.

## Done When

- Public transcript artifacts no longer need to be configured through
  `cast_private_media`.
- Private sidecars and voice references remain private by default.
- Existing deployments keep working without immediate settings changes.
- `python-podcast` can replace its `cast_private_media` public-S3 workaround
  with an explicit public transcript storage alias.
