# Generated by Django 3.2.6 on 2021-08-06 14:50

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cast", "0009_alter_post_body"),
    ]

    operations = [
        migrations.RenameField(
            model_name="blog",
            old_name="intro",
            new_name="description",
        ),
    ]
