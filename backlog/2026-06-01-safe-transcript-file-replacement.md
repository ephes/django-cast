# Safe Transcript File Replacement

## Status

Implemented for django-cast 0.2.58 in commit `8485cdfc`. This note records
the incident and planning context for that slice; the current user-facing fix is
documented in `docs/releases/0.2.58.rst`.

## Summary

Make transcript artifact replacement robust against storage write failures.

Before the django-cast 0.2.58 fix, replacement paths deleted the existing stored
object before uploading the replacement:

- `src/cast/voxhelm.py::replace_file`
- `src/cast/models/transcript.py::_write_transcript_json`

If the storage backend rejects the upload, the database row can still point at
the old filename while the old object has already been deleted. The transcript
then becomes unreadable until restored from backup.

## Production Failure Mode

Django Chat staging hit this on 2026-06-01 while fixing a transcript echo in
audio 23 (`event-sourcing-chris-may`). An S3 `PutObject` failure occurred after
the old `podlove` artifact had been deleted and before the replacement upload
completed. Reads for other artifacts still worked, but `podlove_data` returned
zero segments because the referenced object was missing.

The episode was recovered from a backup and repaired with an operator script
that writes the replacement object first, persists the field, then deletes the
old object.

## Desired Behavior

Use write-new-then-delete-old semantics for transcript artifact replacement:

1. Write the replacement under a fresh object name.
2. Point the `FileField` at the new object and save the model row.
3. Delete the old object only after the DB save succeeds.
4. If a later write or DB save fails, leave the old DB reference and old object
   intact, and best-effort delete any newly written replacement objects.

Avoid relying on overwrite-in-place behavior. Storage backends differ on
overwrite semantics, and object stores can fail independently from the database.

## Original Candidate Implementation Points

- Add a shared helper for safe replacement, likely near the transcript/Voxhelm
  storage code instead of duplicating the pattern.
- Update `src/cast/voxhelm.py::replace_file`.
- Update `src/cast/models/transcript.py::_write_transcript_json`.
- Consider whether WebVTT rewrites or future transcript upload/import paths
  should use the same helper.

## Original Test Plan

Add focused tests with a fake field/storage that prove:

- an upload failure does not call `delete()` on the old object;
- a successful replacement writes before old-object deletion;
- if multiple artifact writes are grouped and a later step fails, already
  written new objects are cleaned up while old objects remain;
- after a successful model save, old objects are deleted as cleanup.

## Original Done When

- Transcript regeneration and transcript JSON rewrite paths no longer have a
  window where neither the old nor the new artifact exists.
- Failure-order tests cover the old production failure mode.
- Release notes mention the storage-safety fix.
