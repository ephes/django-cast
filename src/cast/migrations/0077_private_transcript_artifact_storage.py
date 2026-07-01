from django.db import migrations, models

import cast.private_storage


def keep_transcript_artifacts_in_place(apps, schema_editor):
    """Public transcript artifacts must not be moved or deleted during upgrade."""


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0076_add_media_choose_permissions"),
    ]

    operations = [
        # This migration originally moved public transcript artifacts into
        # private storage and deleted the default-storage originals. Patch the
        # unreleased migration in place so fresh upgraders never run the
        # destructive copy/delete step before the corrected field storage is
        # active.
        migrations.RunPython(keep_transcript_artifacts_in_place, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name="transcript",
            name="dote",
            field=models.FileField(
                blank=True,
                help_text="The DOTe json format for feed / podcatchers",
                null=True,
                storage=cast.private_storage.get_transcript_storage,
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
                storage=cast.private_storage.get_transcript_storage,
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
                storage=cast.private_storage.get_transcript_storage,
                upload_to="cast_transcript/",
                verbose_name="WebVTT Transcript",
            ),
        ),
    ]
