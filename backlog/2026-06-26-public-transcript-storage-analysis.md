# Analysis: Public Transcript Storage vs. Private Media Storage

Date: 2026-06-26

Status: Historical analysis for the implemented `cast_public_transcripts`
storage split.

Related backlog item:
[2026-06-26-public-transcript-storage.md](2026-06-26-public-transcript-storage.md).

## Context

A `python-podcast` production incident exposed a naming and storage-boundary
problem in django-cast.

The production site intentionally publishes transcripts:

- public transcript HTML pages expose the text;
- player transcript APIs expose cue text and approved speaker labels;
- podcast feeds link to transcript endpoints;
- PodcastIndex/DOTe and WebVTT output are meant for podcast clients.

Despite that, django-cast stores `Transcript.podlove`, `Transcript.vtt`, and
`Transcript.dote` through `get_private_media_storage()`, backed by the
`cast_private_media` storage alias.

When `python-podcast` configured truly private media separately, public
transcript reads broke because django-cast still tried to read the existing
public S3 transcript objects through the private alias. The emergency production
fix was to point `cast_private_media` back at the public S3 media bucket.

That restored the site, but it is not the right abstraction.

## What Is Public

These artifacts are publishable output:

- Podlove JSON transcript
- WebVTT transcript
- DOTe / PodcastIndex JSON transcript
- approved speaker labels written into those artifacts

They may be served directly by Django views or by a public object store/CDN, but
their content is already public once an episode transcript is published.

## What Is Private

These artifacts should remain private:

- known-speaker suggestion sidecars (`Transcript.speakers`);
- raw per-segment Voxhelm candidate data;
- confidence/margin/uncertainty metadata;
- raw diarization labels before editorial mapping;
- contributor voice reference clips or source ranges;
- any future raw processing artifacts that are not part of public transcript
  output.

The known-speaker sidecar is editorial state. It can contain uncertain identity
guesses and raw model output. It is not the same thing as the reviewed public
speaker labels in Podlove, WebVTT, or DOTe.

## Why The Current Workaround Is Risky

Pointing `cast_private_media` at a public bucket is tolerable only because the
current public transcript fields are the main users of that alias in the
affected deployment. It is still risky:

- the alias name communicates the wrong privacy contract;
- a future django-cast private artifact could accidentally use the same alias
  and become public;
- operators cannot configure public transcripts and private raw artifacts
  independently;
- security reviews have to reason about intent from deployment-specific storage
  overrides instead of model/storage names.

The workaround also makes documentation awkward: "private media points to public
S3" is correct for the emergency shape, but it is not a durable product story.

## Options Considered

### Option 1: Keep The Existing Workaround

Leave `Transcript.podlove`, `Transcript.vtt`, and `Transcript.dote` on
`cast_private_media`, and tell public transcript sites to point that alias at a
public storage backend.

Pros:

- no django-cast code change;
- lowest immediate deployment risk;
- current production workaround already works.

Cons:

- misleading name;
- high future footgun risk;
- private and public artifacts cannot be separated cleanly;
- consumer docs have to encode an implementation accident.

This is acceptable only as a short-term production stabilizer.

### Option 2: Add A Dedicated Public Transcript Storage Alias

Add a new helper and storage alias for transcript artifacts, with fallback to
the old alias for backward compatibility.

Example shape:

```python
STORAGES = {
    "cast_public_transcripts": {"BACKEND": "public-or-site-specific-storage"},
    "cast_private_media": {"BACKEND": "private-storage"},
    "cast_voice_references": {"BACKEND": "private-storage"},
}
```

Pros:

- matches the product contract;
- keeps known-speaker sidecars private;
- gives deployments an obvious setting;
- preserves existing behavior via fallback;
- lets `python-podcast` remove its workaround without changing transcript URLs.

Cons:

- requires django-cast code, docs, tests, and release notes;
- consumers that want the cleaner setup must add one new storage alias.

This is the recommended path.

### Option 3: Use A Dedicated Public Bucket Or Prefix

Sites can configure the new transcript alias to a separate public bucket or
prefix, e.g. only `cast_transcript/`.

Pros:

- smaller public object surface than sharing the general media bucket;
- clearer IAM/bucket-policy boundaries;
- still compatible with public transcript URLs and feeds.

Cons:

- operationally more moving parts;
- not sufficient without the django-cast alias split.

This is a good deployment hardening option after Option 2 exists.

### Option 4: Store Transcripts Privately And Serve Public Views

Store Podlove/VTT/DOTe privately, then expose unauthenticated Django endpoints
for all public consumers.

Pros:

- one canonical private object store;
- all public access goes through Django authorization/caching code.

Cons:

- more operational risk for podcast clients, feeds, CDN behavior, and caching;
- the transcript content is public anyway;
- creates more server dependency for static transcript artifacts;
- does not remove the need to distinguish reviewed public labels from private
  known-speaker sidecars.

This is not the preferred default for django-cast.

### Option 5: Canonical Private Raw Artifacts Plus Published Public Copies

Keep raw/editorial transcript artifacts private, and publish separate public
copies after review.

Pros:

- clean editorial model;
- useful if django-cast later supports transcript draft/review workflows.

Cons:

- more state, workflows, invalidation, and migration complexity;
- unnecessary for current published transcript behavior.

This may become useful later, but it is overkill for the current storage bug.

## Recommended Migration Path

1. Add `get_transcript_storage()` in django-cast.
2. Resolve it from a new storage alias such as `cast_public_transcripts`.
3. Fall back to an explicitly configured `cast_private_media` alias if the new
   alias is absent, preserving deployments that already adopted the temporary
   behavior.
4. Fall back to Django's default storage if neither alias is configured,
   preserving the original public-media behavior and avoiding accidental local
   private-filesystem moves.
5. Update `Transcript.podlove`, `Transcript.vtt`, and `Transcript.dote` to use
   `get_transcript_storage()`.
6. Keep `Transcript.speakers` and contributor voice references on private
   storage.
7. Patch migration `0077_private_transcript_artifact_storage` so fresh
   deployments do not move or delete public transcript artifacts before the new
   storage helper is active.
8. Document the intended storage split.
9. Add release notes with an upgrade example.
10. Update `python-podcast` to configure the new public transcript alias and
   return `cast_private_media` to genuinely private storage or remove the alias
   override if unused.

## Compatibility Notes

This should not require a data migration. Existing `FileField.name` values are
relative object names such as `cast_transcript/...`. The storage backend used to
open those names changes by field configuration.

Deployments that already store transcript artifacts in a private filesystem can
continue doing so by configuring the new transcript alias to that filesystem.
Deployments that publish transcript artifacts from S3 can configure the alias to
public S3.

The key is that this choice should be explicit and transcript-specific.

## Test Considerations

The implementation should cover:

- helper resolution when `cast_public_transcripts` is configured;
- fallback behavior when `cast_public_transcripts` is absent but `cast_private_media`
  is explicitly configured;
- fallback behavior to default storage when neither alias is configured;
- `Transcript.podlove`, `vtt`, and `dote` use the transcript helper;
- `Transcript.speakers` continues using voice/private storage;
- Voxhelm `_save_artifacts()` writes public artifacts through transcript
  storage and sidecars through private storage;
- transcript read helpers, safe replacement, speaker rewrites, and WebVTT
  updates still work with the split.

## Decision

Implement Option 2 first. Option 3 can be a deployment recommendation for sites
that want a tighter public transcript bucket or prefix. Avoid Option 4 unless a
site has a specific requirement to proxy all transcript objects through Django.
