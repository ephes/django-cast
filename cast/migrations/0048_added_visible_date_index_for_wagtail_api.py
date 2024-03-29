# Generated by Django 4.1.8 on 2023-05-19 11:23

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0047_alter_episode_podcast_audio"),
    ]

    operations = [
        migrations.AlterField(
            model_name="post",
            name="visible_date",
            field=models.DateTimeField(
                db_index=True,
                default=django.utils.timezone.now,
                help_text="The visible date of the post which is used for sorting.",
            ),
        ),
    ]
