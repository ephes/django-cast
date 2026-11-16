######
Backup
######

***********************
Database Backup/Restore
***********************

There's no unified way to backup and restore a database. For my personal projects
I use ansible playbooks like this:

* `backup <https://github.com/ephes/homepage/blob/main/deploy/backup_database.yml>`_
* `restore <https://github.com/ephes/homepage/blob/main/deploy/restore_database.yml>`_

It would be nice to be able to fetch all the relevant database contents by just
reading from the cast REST-api and recreate the contents by just writing to
another cast REST-api. This would make it possible to backup and restore really
easy. But for now you have to do something database specific.

Howto Restore a Database
========================

Use the database-native restore tooling or the backup/restore playbooks maintained
by your deployment project. Fetch the backup with that project's documented
procedure, verify it against a disposable local database, and select the intended
target explicitly before restoring. The old repository-specific
``production-db-to-local`` helper is no longer provided.

********************
Media Backup/Restore
********************

Backup and restore are supported by the `media_backup` and `media_restore`
:ref:`management commands <cast_management_commands>`.

``media_backup`` only copies files that are missing in the backup. After
replacing a file in place (``media_replace``), run
``media_backup --refresh-changed`` so the backup does not keep the old bytes
under the same path.

Both commands report ``copied``, ``refreshed``, ``unchanged`` and ``errors``
counts and continue processing independent paths after a file error. Any failed
path causes a nonzero command exit, including default backup and restore.
Successful sibling copies remain available. Restore still copies missing paths
only and never overwrites existing production files.

Storage inventories must list direct child names, never absolute paths, parent
components, embedded separators, drive syntax or NULs. Unicode child names are
supported. Backup/restore refuse an unsafe listing before copying its files.
Traversal is iterative and limited to 64 levels below the starting prefix,
10,000 directories (including that prefix), and 1,000,000 file entries. Duplicate
directory prefixes are refused. Exceeding a limit reports an incomplete inventory
and a nonzero exit; files already copied remain intact. These are finite safety
ceilings, not an assurance that a backend's individual ``listdir`` call cannot
block or allocate a large response. Colons are accepted in names (they are
ordinary in POSIX file names and S3 keys) except on Windows. ``media_stale`` uses the same bounded walker
and refuses an unsafe inventory before deleting files.

Missing copies now use the same owned temporary staging as refreshes. A failed
staging save removes both the requested and any returned temporary key; a failed
final save for a previously absent target also removes that invocation's partial
final key, allowing an ordinary retry. Cleanup errors remain visible alongside
the original failure. An existing staging name is a conflict and is never
removed. A killed process can still leave scratch/partial keys: inspect these
before retrying; this is exception recovery, not a crash transaction.

Publication uses a nonblocking OS file lock shared by cooperating backup/restore
invocations on the same host, OS user and temporary directory (``TMPDIR``). The
lock file lives in an owner-only directory ``django-cast-media-sync-uid-<uid>``
inside the temporary directory and is opened without following symlinks; a
directory that is not private to the current user is refused rather than used.
A competing invocation reports a publication conflict; rerun it after the active
writer finishes. The lock is released on process exit; its file is retained to
keep the lock identity stable. All media publications share this lock, including
different keys. Existence checks and unchanged decisions also hold the lock,
so they cannot count another sync's in-flight partial key as complete.
Source, staged bytes and target content are checked again before
publication; a changed source or target is refused, retaining the newer target.
Concurrent source writers must use atomic replacement and leave the source
stable through publication. These checks cannot provide backend compare-and-swap.

Do not run publishers from other hosts, users or isolated temporary directories,
or write directly to the target, during sync. Django's generic storage API has
no conditional final save; such writers are outside the lock's guarantee,
including recovery of a failed missing-copy save. Cross-host publication needs
backend-specific conditional writes and is unsupported. Existing-file final
write failures remain backend-dependent as described in the command reference.

Every full read used for hashing (comparison of source and target, and each
publication-verification read of target, source and staged copy) has its own
ceiling of 16 GiB of bytes and a deadline of 300 seconds, extended for large
objects to their reported size at 4 MiB/s (at most the time 16 GiB takes at that
rate, about 68 minutes). Missing copies are subject to the same
per-read ceilings, since they are staged and verified like refreshes. Reads
request at most 1 MiB (or the remaining budget plus one overflow byte). Oversized, growing or delayed streams cause an explicit
path error before publication. A refused comparison never counts as unchanged.
The deadline is checked around synchronous reads; configure backend I/O timeouts
as well, since Python cannot interrupt an individual blocked storage call.
These ceilings cover hashing; backend-managed ``save`` I/O (the staging upload
and the final save) is not charged to any of them.

A failed final refresh can leave partial destination bytes. The command retains
a SHA-256-verified complete recovery copy and reports its exact reserved
``.django-cast-refresh-<random>.tmp`` key. Backup and restore skip
these keys. Retry with the original source when available; otherwise inspect
and explicitly recover from the reported key, verify the destination, and
delete the key manually. See :doc:`/reference/management-commands` for details.
A failed missing copy keeps no recovery key: its partial final key is removed
and an ordinary retry copies the file again.

Once we have a unified way to backup and restore the database, we can also
integrate the media backup and restore into a single command.

****************************
Transcript previous versions
****************************

``Transcript.previous_version`` is a single private JSON bundle with embedded
file bytes and editorial speaker mappings. Include ``CAST_PRIVATE_MEDIA_ROOT``
or the configured private storage in backups. The admin swaps this bundle with
the current version on restore; it is not an archive of every revision and does
not replace normal database/media backups. Delete the transcript to remove its
previous-version bundle. Never expose private storage through the media server.

Previous-version capture admits at most 10 MiB per artifact and 30 MiB of raw
file bytes in total across public artifacts and private sidecars. Reads remain
bounded if a stored file grows. The complete JSON bundle, including base64 and
mapping metadata, must fit within 42 MiB. Replacement refuses before changing
current files if these limits are exceeded or storage is unavailable; the
transcript edit view shows the refusal as a form error. Only
``FileNotFoundError`` permits omitting a missing artifact from the backup; a
restored version clears fields for those omitted files.

Restore reserves the transcript row before selecting and reading its backup.
A stale editor cannot restore an obsolete backup generation. JSON admission
rejects repeated members, excessive nesting, unsupported schema versions,
invalid file bytes and invalid or duplicate speaker mappings before staging
files or deleting mappings. Version-1 bundles remain supported; deleted
contributors are restored as mappings needing review. Interrupted capture or
restore removes owned staged files while preserving the original failure.

Backup deletion runs after the database commit. If storage deletion fails, the
transcript remains deleted and the request succeeds; the ``cast.receivers``
logger records the exact ``recovery storage key``. Retain that log and retry
removing only that key from the configured private storage after recovery.
