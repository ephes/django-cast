# Transcript Speaker-Mapping Fingerprints on S3 Storage

## Summary

Fix read-time public speaker mappings so they do not depend on the order in
which transcript `FileField` artifacts are opened.

On S3-backed storage, django-storages `FieldFile` objects can raise
`ValueError("Cannot reopen file with a new mode.")` when the same field is
opened again on the same model instance. django-cast catches that while reading
transcript artifacts for labels/fingerprints, but the catch can silently change
which artifact bytes contribute to `Transcript.transcript_artifact_fingerprint()`.

That makes approved `TranscriptSpeakerMapping` rows look stale or non-current in
public views, even when the DB rows are valid.

## Production Failure Mode

Django Chat staging hit this on 2026-06-01 while fixing the speaker labels for:

- `boost-your-django-dx-adam-johnson-ep105-replay`
- `boost-your-django-dx-adam-johnon`

Both episodes had correct `EpisodeContributor` rows and approved
`TranscriptSpeakerMapping` rows:

- `Speaker 1` → Carlton Gibson
- `Speaker 2` → Adam Johnson
- `Speaker 3` → Will Vincent

But public Podlove API responses still returned zero transcript contributors
and sanitized all raw `Speaker N` labels. The cause was order-dependent
fingerprinting:

1. Public Podlove serialization reads `transcript.podlove_data`.
2. `public_speaker_mapping_for_transcript()` calls `_current_raw_speaker_labels()`.
3. `_current_raw_speaker_labels()` calls `transcript.get_speaker_labels()`, which
   opens transcript artifacts.
4. `_current_mapping_rows()` then calls `transcript.transcript_artifact_fingerprint()`.
5. On S3-backed `FieldFile` instances, some artifacts can no longer be reopened
   in the requested mode, so the fingerprint differs from the fingerprint stored
   when mapping rows were approved.

The staging workaround was to set the approved mapping rows to the fingerprint
produced by the deployed public read order. That made public output correct, but
it is not a durable library fix.

## Desired Behavior

`Transcript.transcript_artifact_fingerprint()` should return the same value for
the same stored artifacts regardless of previous reads on the model instance.

Acceptable implementation directions:

- Read artifact bytes via `field.storage.open(field.name, mode)` instead of
  reopening the existing `FieldFile` object.
- Compute the fingerprint before any helper opens transcript artifacts for raw
  label extraction.
- Cache raw artifact bytes/fingerprint per operation in a way that does not
  expose stale values across artifact replacement.

Prefer a fix that makes the low-level file-read helper stable, because the same
reopen behavior can affect other transcript paths.

## Tests

Add focused regression tests with a fake storage/field or django-storages-style
test double that raises on reopening the same field in a new mode.

Test cases should prove:

- `transcript_artifact_fingerprint()` is stable before and after reading
  `podlove_data`, `dote_data`, `vtt`, or `get_speaker_labels()` on the same
  transcript instance.
- `public_speaker_mapping_for_transcript()` returns approved mappings when rows
  match the stable fingerprint.
- `AudioPodloveSerializer` and transcript page rendering apply approved mappings
  and emit public contributors, not sanitized blank speakers, under S3-like
  reopen behavior.

## Done When

- Approved read-time speaker mappings work on S3-backed transcript storage
  without fingerprint workarounds.
- Public Podlove API and transcript views keep speaker labels consistent after
  prior artifact reads on the same model instance.
- Release notes mention the S3-backed speaker-mapping fingerprint fix.
