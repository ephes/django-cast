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

.. code-block:: shell

    python commands.py production-db-to-local
    cd backups
    mv 2023-09-18-22:17:27_homepage.sql.gz db.staging.psql.gz
    cd ..
    cd deploy
    ansible-playbook restore_database.yml --limit staging

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
block or allocate a large response. ``media_stale`` uses the same bounded walker
and refuses an unsafe inventory before deleting files.

Missing copies now use the same owned temporary staging as refreshes. A failed
staging save removes both the requested and any returned temporary key; a failed
final save for a previously absent target also removes that invocation's partial
final key, allowing an ordinary retry. Cleanup errors remain visible alongside
the original failure. An existing staging name is a conflict and is never
removed. A killed process can still leave scratch/partial keys: inspect these
before retrying; this is exception recovery, not a crash transaction.

Publication uses a nonblocking OS file lock shared by cooperating backup/restore
invocations on the same host, OS user and temporary directory (``TMPDIR``).
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

Content comparison shares a ceiling of 16 GiB of bytes and 300 seconds between
source and target hashing. Publication verification has its own shared ceiling
across all of its hashes. Reads request at most 1 MiB (or the remaining budget
plus one overflow byte). Oversized, growing or delayed streams cause an explicit
path error before publication. A refused comparison never counts as unchanged.
The deadline is checked around synchronous reads; configure backend I/O timeouts
as well, since Python cannot interrupt an individual blocked storage call.
These ceilings cover hashing, not backend-managed ``save`` I/O.

Once we have a unified way to backup and restore the database, we can also
integrate the media backup and restore into a single command.
