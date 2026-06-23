from django.core.files.storage import default_storage
from django.db import migrations, models

import cast.private_storage


TRANSCRIPT_ARTIFACT_FIELDS = ("podlove", "vtt", "dote")


def move_transcript_artifacts_to_private_storage(apps, schema_editor):
    Transcript = apps.get_model("cast", "Transcript")
    private_storage = cast.private_storage.get_private_media_storage()

    for transcript in Transcript.objects.iterator():
        changed_fields = []
        for field_name in TRANSCRIPT_ARTIFACT_FIELDS:
            field_file = getattr(transcript, field_name)
            original_name = getattr(field_file, "name", "")
            if not original_name:
                continue
            if private_storage.exists(original_name) or not default_storage.exists(original_name):
                continue
            with default_storage.open(original_name, "rb") as source_file:
                private_name = private_storage.save(original_name, source_file)
            if private_name != original_name:
                setattr(transcript, field_name, private_name)
                changed_fields.append(field_name)
            default_storage.delete(original_name)
        if changed_fields:
            transcript.save(update_fields=changed_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0076_add_media_choose_permissions"),
    ]

    operations = [
        migrations.RunPython(move_transcript_artifacts_to_private_storage, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name="transcript",
            name="dote",
            field=models.FileField(
                blank=True,
                help_text="The DOTe json format for feed / podcatchers",
                null=True,
                storage=cast.private_storage.get_private_media_storage,
                upload_to="cast_transcript/",
                verbose_name="DOTe Transcript",
            ),
        ),
        migrations.AlterField(
            model_name="transcript",
            name="podlove",
            field=models.FileField(
                blank=True,
                help_text="The transcript format for the Podlove Web Player",
                null=True,
                storage=cast.private_storage.get_private_media_storage,
                upload_to="cast_transcript/",
                verbose_name="Podlove Transcript",
            ),
        ),
        migrations.AlterField(
            model_name="transcript",
            name="vtt",
            field=models.FileField(
                blank=True,
                help_text="The WebVTT format for feed / podcatchers",
                null=True,
                storage=cast.private_storage.get_private_media_storage,
                upload_to="cast_transcript/",
                verbose_name="WebVTT Transcript",
            ),
        ),
    ]
