from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("wagtailcore", "0096_pages_view_restriction_types"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cast", "0064_voxhelmsettings"),
    ]

    operations = [
        migrations.CreateModel(
            name="TranscriptGeneration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                ("task_ref", models.CharField(max_length=255)),
                ("voxhelm_job_id", models.CharField(blank=True, max_length=255)),
                ("task_result_id", models.CharField(blank=True, max_length=255)),
                ("source_url", models.URLField(blank=True, max_length=1000)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "audio",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transcript_generation",
                        to="cast.audio",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="wagtailcore.site",
                    ),
                ),
            ],
            options={"ordering": ("-updated_at",)},
        ),
    ]
