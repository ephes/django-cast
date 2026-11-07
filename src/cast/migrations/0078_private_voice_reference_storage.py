import hashlib
import logging
from uuid import uuid4
from pathlib import PurePosixPath

from django.core.files.storage import default_storage
from django.db import connections, migrations, models, transaction

import cast.models.contributors


PRIVATE_FILE_FIELDS = (
    ("ContributorVoiceReference", "clip"),
    ("Transcript", "speakers"),
)


def _digest(storage, name):
    digest = hashlib.sha256()
    with storage.open(name, "rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.digest()


def _release_source(apps, alias, storage, original, private_name, expected):
    # Shared storage can serve multiple databases; retain sources for manual
    # cleanup when we cannot prove exclusive ownership across all of them.
    if len(list(connections)) != 1 or original == private_name:
        return
    tables = set(connections[alias].introspection.table_names())
    for model in apps.get_models():
        if model._meta.db_table not in tables:
            continue
        for field in model._meta.fields:
            if isinstance(field, models.FileField):
                if model.objects.using(alias).filter(**{field.name: original}).exists():
                    return
    try:
        if _digest(storage, private_name) == expected and _digest(default_storage, original) == expected:
            default_storage.delete(original)
    except (OSError, ValueError):
        logging.getLogger(__name__).warning("Private storage migration retained a source for manual cleanup.")


def move_voice_reference_files_to_private_storage(apps, schema_editor):
    private_storage = cast.models.contributors.get_voice_reference_storage()
    alias = schema_editor.connection.alias
    for model_name, field_name in PRIVATE_FILE_FIELDS:
        model = apps.get_model("cast", model_name)
        for instance in model.objects.using(alias).iterator():
            original_name = getattr(getattr(instance, field_name), "name", "")
            if not original_name or not default_storage.exists(original_name):
                continue
            expected = _digest(default_storage, original_name)
            # A unique destination preserves collisions and makes retries safe,
            # including when public and private backends share a namespace.
            candidate = f"cast_private_migration/{uuid4().hex}{PurePosixPath(original_name).suffix}"
            max_length = model._meta.get_field(field_name).max_length
            with default_storage.open(original_name, "rb") as source_file:
                private_name = private_storage.save(candidate, source_file, max_length=max_length)
            if len(private_name) > max_length or _digest(private_storage, private_name) != expected:
                raise ValueError("Private storage migration copy verification failed; original retained.")
            setattr(instance, field_name, private_name)
            instance.save(using=alias, update_fields=[field_name])
            transaction.on_commit(
                lambda original=original_name, destination=private_name, digest=expected: _release_source(
                    apps, alias, private_storage, original, destination, digest
                ), using=alias, robust=True,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0077_private_transcript_artifact_storage"),
    ]

    operations = [
        migrations.RunPython(move_voice_reference_files_to_private_storage, reverse_code=migrations.RunPython.noop),
    ]
