# Generated by Django 3.2.5 on 2021-07-12 09:19

import django.db.models.deletion
import taggit.managers
import wagtail.blocks
import wagtail.fields
import wagtail.models
import wagtail.embeds.blocks
import wagtail.images.blocks
from django.db import migrations, models

import cast.blocks


class Migration(migrations.Migration):

    dependencies = [
        ("wagtailcore", "0062_comment_models_and_pagesubscription"),
        ("taggit", "0003_taggeditem_add_unique_index"),
        ("cast", "0007_alter_post_body"),
    ]

    operations = [
        migrations.AddField(
            model_name="video",
            name="collection",
            field=models.ForeignKey(
                default=wagtail.models.get_root_collection_id,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="wagtailcore.collection",
                verbose_name="collection",
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="tags",
            field=taggit.managers.TaggableManager(
                blank=True, help_text=None, through="taggit.TaggedItem", to="taggit.Tag", verbose_name="tags"
            ),
        ),
        migrations.AddField(
            model_name="video",
            name="title",
            field=models.CharField(default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="post",
            name="body",
            field=wagtail.fields.StreamField(
                [
                    ("heading", wagtail.blocks.CharBlock(form_classname="full title")),
                    ("paragraph", wagtail.blocks.RichTextBlock()),
                    ("image", wagtail.images.blocks.ImageChooserBlock(template="cast/image.html")),
                    ("gallery", cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock())),
                    ("embed", wagtail.embeds.blocks.EmbedBlock()),
                    ("video", cast.blocks.VideoChooserBlock(template="cast/video/video.html")),
                ]
            ),
        ),
    ]
