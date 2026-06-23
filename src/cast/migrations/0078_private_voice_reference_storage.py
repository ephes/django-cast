from django.core.files.storage import default_storage
from django.db import migrations

import cast.models.contributors


PRIVATE_FILE_FIELDS = (
    ("ContributorVoiceReference", "clip"),
    ("Transcript", "speakers"),
)


def move_voice_reference_files_to_private_storage(apps, schema_editor):
    private_storage = cast.models.contributors.get_voice_reference_storage()

    for model_name, field_name in PRIVATE_FILE_FIELDS:
        model = apps.get_model("cast", model_name)
        for instance in model.objects.iterator():
            field_file = getattr(instance, field_name)
            original_name = getattr(field_file, "name", "")
            if not original_name:
                continue
            if private_storage.exists(original_name) or not default_storage.exists(original_name):
                continue
            with default_storage.open(original_name, "rb") as source_file:
                private_name = private_storage.save(original_name, source_file)
            if private_name != original_name:
                setattr(instance, field_name, private_name)
                instance.save(update_fields=[field_name])
            default_storage.delete(original_name)


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0077_private_transcript_artifact_storage"),
    ]

    operations = [
        migrations.RunPython(move_voice_reference_files_to_private_storage, reverse_code=migrations.RunPython.noop),
    ]
