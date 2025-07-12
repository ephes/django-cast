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

Once we have a unified way to backup and restore the database, we can also
integrate the media backup and restore into a single command.
