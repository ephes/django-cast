# Generated by Django 3.2.7 on 2021-09-22 09:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cast", "0018_alter_chaptermark_start"),
    ]

    operations = [
        migrations.AlterField(
            model_name="chaptermark",
            name="start",
            field=models.TimeField(verbose_name="Start time of chaptermark"),
        ),
    ]
