# Generated by Django 5.0.4 on 2024-05-08 09:52

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cast", "0055_alter_podcast_itunes_artwork"),
        ("wagtailimages", "0025_alter_image_file_alter_rendition_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="cover",
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
