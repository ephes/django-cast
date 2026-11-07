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
        artifact_digest = digest.copy()
        try:
            with file_field.storage.open(file_field.name, "rb") as file:
                artifact_digest.update(field_name.encode("utf-8"))
                artifact_digest.update(b"\0")
                for chunk in iter(lambda: file.read(65536), b""):
                    artifact_digest.update(chunk)
        except (FileNotFoundError, OSError, ValueError):
            continue
        saw_content = True
        artifact_digest.update(b"\0")
        digest = artifact_digest
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
