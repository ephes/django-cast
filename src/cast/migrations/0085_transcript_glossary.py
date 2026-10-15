import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0084_transcript_source_fingerprint"),
    ]

    operations = [
        migrations.AddField(
            model_name="contributor",
            name="transcript_variants",
            field=models.TextField(
                blank=True,
                help_text='Private. Misspellings speech recognition produces for this name, one per line as "variant => replacement", for example "John Gould => Jon Gould" or "John => Jon". A line without "=>" is replaced by the display name. Variants apply only to transcripts of episodes that credit this contributor.',
            ),
        ),
        migrations.CreateModel(
            name="TranscriptGlossaryTerm",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="created"
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now, editable=False, verbose_name="modified"
                    ),
                ),
                (
                    "term",
                    models.CharField(
                        help_text='The correct spelling, for example "Gunicorn". Unique per podcast, ignoring case.',
                        max_length=255,
                    ),
                ),
                (
                    "variants",
                    models.TextField(
                        blank=True,
                        help_text='Misspellings speech recognition produces for this term, one per line, for example "Gunacorn". Each variant is replaced by the term automatically in this podcast\'s transcripts, so list only phrases that are always wrong. Common words of the transcript language are refused.',
                    ),
                ),
                ("notes", models.TextField(blank=True, help_text="Internal notes, never shown publicly.")),
                (
                    "podcast",
                    models.ForeignKey(
                        help_text="Podcast whose transcripts use this term.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transcript_glossary_terms",
                        to="cast.podcast",
                    ),
                ),
            ],
            options={
                "verbose_name": "Transcript glossary term",
                "verbose_name_plural": "Transcript glossary terms",
                "ordering": ["podcast_id", "term"],
                "constraints": [
                    models.UniqueConstraint(
                        models.F("podcast"),
                        django.db.models.functions.text.Lower("term"),
                        name="unique_podcast_transcript_glossary_term",
                        violation_error_message="This podcast already has this term.",
                    )
                ],
            },
        ),
    ]
