import hashlib

from django.db import migrations, models

ARTIFACT_FIELDS = ("podlove", "dote", "vtt")


def artifact_fingerprint(transcript) -> str:
    """Hash the stored artifacts like ``Transcript.transcript_artifact_fingerprint``.

    Historical models have no custom methods, so the algorithm is repeated here.
    """
    digest = hashlib.sha256()
    saw_content = False
    for field_name in ARTIFACT_FIELDS:
        file_field = getattr(transcript, field_name)
        if not file_field or not file_field.name:
            continue
        try:
            with file_field.storage.open(file_field.name, "rb") as file:
                content = file.read()
        except (FileNotFoundError, OSError, ValueError):
            continue
        saw_content = True
        digest.update(field_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest() if saw_content else ""


def set_source_fingerprints(apps, schema_editor):
    """Treat the artifacts stored today as received, so approved mappings stay current."""
    Transcript = apps.get_model("cast", "Transcript")
    alias = schema_editor.connection.alias
    transcripts = Transcript.objects.using(alias).only("pk", *ARTIFACT_FIELDS)
    for transcript in transcripts.iterator():
        fingerprint = artifact_fingerprint(transcript)
        if fingerprint:
            Transcript.objects.using(alias).filter(pk=transcript.pk).update(source_fingerprint=fingerprint)


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0083_post_feed_boundary_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="transcript",
            name="source_fingerprint",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Hash of the public Podlove, DOTe and WebVTT artifacts as received from Voxhelm or uploaded. "
                    "Approved speaker mappings stay current while it is unchanged; speaker application does not "
                    "change it."
                ),
                max_length=64,
            ),
        ),
        migrations.RunPython(set_source_fingerprints, migrations.RunPython.noop),
    ]
