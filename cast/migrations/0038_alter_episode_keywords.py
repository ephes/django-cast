# Generated by Django 4.1.6 on 2023-02-07 15:28

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0037_alter_episode_block_alter_episode_explicit_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="episode",
            name="keywords",
            field=models.CharField(
                blank=True,
                default="",
                help_text="A comma-delimited-list of up to 12 words for iTunes\n            searches. Perhaps include misspellings of the title.",
                max_length=255,
            ),
        ),
    ]