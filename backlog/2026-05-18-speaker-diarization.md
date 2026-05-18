# Speaker Diarization

## Context

django-cast can generate transcripts through Voxhelm, but the current flow imports plain transcript artifacts only:
Podlove JSON, DOTe JSON, and WebVTT. We do not currently identify speakers or store speaker-labeled transcript data
as first-class content.

This is worth shaping because podcasts often have multiple recurring speakers. Even generic labels like
`Speaker 1` / `Speaker 2` would make transcripts easier to scan, and named speaker attribution could later connect
to episode contributors.

## Voxhelm Feasibility Check

Checked local Voxhelm at `/Users/jochen/projects/voxhelm` on 2026-05-18.

Findings:

- Voxhelm decision D-12 explicitly deferred diarization as a later milestone. The recorded reason was the extra
  dependency and operational shape around `pyannote.audio`, Hugging Face tokens, and merging diarization output back
  into transcription segments.
- The shipped batch API currently accepts `job_type=transcribe` and `job_type=synthesize`; there is no `diarize`
  job type or transcription diarization option.
- The normalized transcription model has segments with `id`, `start`, `end`, and `text`, but no speaker field.
- Voxhelm already renders DOTe and Podlove artifacts server-side. Both formats currently set their speaker fields to
  empty strings, which is a useful integration point once speaker labels exist.
- django-cast already consumes Voxhelm's `podlove`, `dote`, and `vtt` artifacts directly. If Voxhelm fills speaker
  fields in those artifacts without changing artifact names, the first django-cast import change can stay small.

Assessment:

- Voxhelm work: medium to large. It needs a diarization backend, model/config management, audio normalization policy,
  alignment from diarization turns to STT segments, an internal speaker-labeled segment schema, output rendering
  changes, tests, and operational docs.
- django-cast work after Voxhelm support: small to medium for generic speaker labels in existing transcript files;
  medium if we also add named speaker editing, contributor mapping, or public speaker metadata.

## Open Questions

- Should diarization be requested by default for generated podcast transcripts, or controlled per site/audio item?
- Should Voxhelm expose this as `job_type=diarize`, as an option on `job_type=transcribe`, or both?
- Which speaker identity should django-cast store: generic labels from the transcript artifact, editor-assigned names,
  links to episode contributors, or a combination?
- What should happen when diarization quality is poor or speakers overlap?
- Does WebVTT need speaker labels for the first slice, or are DOTe and Podlove enough?

## Suggested First Slice

1. Add a Voxhelm spike using one diarization backend on representative German and English podcast episodes; this is
   tracked as C21 in the Voxhelm planning docs at `../voxhelm/specs/delivery-chunks.md` from the django-cast root.
2. Extend Voxhelm's internal transcript segment shape with an optional speaker label.
3. Render speaker labels into DOTe `speakerDesignation` and Podlove `speaker` / `voice` fields.
4. Keep django-cast's current artifact import path and verify that existing transcript display/feed behavior remains
   stable when the speaker fields are populated.
5. Decide separately whether django-cast needs named speaker editing and contributor mapping.
