# Generated by Django 3.2.6 on 2021-08-30 09:22

import django.db.models.deletion
import taggit.managers
import wagtail.models.collections
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("taggit", "0003_taggeditem_add_unique_index"),
        ("wagtailcore", "0062_comment_models_and_pagesubscription"),
        ("cast", "0015_delete_blogindexpage"),
    ]

    operations = [
        migrations.AddField(
            model_name="audio",
            name="collection",
            field=models.ForeignKey(
                default=wagtail.models.collections.get_root_collection_id,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="wagtailcore.collection",
                verbose_name="collection",
            ),
        ),
        migrations.AddField(
            model_name="audio",
            name="tags",
            field=taggit.managers.TaggableManager(
                blank=True, help_text=None, through="taggit.TaggedItem", to="taggit.Tag", verbose_name="tags"
            ),
        ),
    ]
