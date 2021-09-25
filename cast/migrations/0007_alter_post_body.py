# Generated by Django 3.2.5 on 2021-07-01 08:34

import wagtail.core.blocks
import wagtail.core.fields
import wagtail.embeds.blocks
import wagtail.images.blocks
from django.db import migrations

import cast.blocks


class Migration(migrations.Migration):

    dependencies = [
        ("cast", "0006_auto_20210628_1628"),
    ]

    operations = [
        migrations.AlterField(
            model_name="post",
            name="body",
            field=wagtail.core.fields.StreamField(
                [
                    ("heading", wagtail.core.blocks.CharBlock(form_classname="full title")),
                    ("paragraph", wagtail.core.blocks.RichTextBlock()),
                    ("image", wagtail.images.blocks.ImageChooserBlock(template="cast/image/image.html")),
                    ("gallery", cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock())),
                    ("embed", wagtail.embeds.blocks.EmbedBlock()),
                ]
            ),
        ),
    ]
