# Generated by Django 5.0.4 on 2024-06-12 16:10

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cast", "0057_rename_cover_image_and_add_alt_text"),
        ("wagtailimages", "0025_alter_image_file_alter_rendition_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="blog",
            name="cover_alt_text",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="blog",
            name="cover_image",
            field=models.ForeignKey(
                blank=True,
                help_text="An optional cover image.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="wagtailimages.image",
            ),
        ),
    ]
