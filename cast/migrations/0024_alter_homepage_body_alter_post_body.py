# Generated by Django 4.1.4 on 2022-12-10 07:38

import cast.blocks
from django.db import migrations
import wagtail.blocks
import wagtail.embeds.blocks
import wagtail.fields
import wagtail.images.blocks


class Migration(migrations.Migration):

    dependencies = [
        ("cast", "0023_alter_spamfilter_model"),
    ]

    operations = [
        migrations.AlterField(
            model_name="homepage",
            name="body",
            field=wagtail.fields.StreamField(
                [
                    ("heading", wagtail.blocks.CharBlock(form_classname="full title")),
                    ("paragraph", wagtail.blocks.RichTextBlock()),
                    ("image", wagtail.images.blocks.ImageChooserBlock(template="cast/image/image.html")),
                    ("gallery", cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock())),
                ],
                use_json_field=True,
            ),
        ),
        migrations.AlterField(
            model_name="post",
            name="body",
            field=wagtail.fields.StreamField(
                [
                    (
                        "overview",
                        wagtail.blocks.StreamBlock(
                            [
                                ("heading", wagtail.blocks.CharBlock(form_classname="full title")),
                                ("paragraph", wagtail.blocks.RichTextBlock()),
                                ("image", wagtail.images.blocks.ImageChooserBlock(template="cast/image/image.html")),
                                ("gallery", cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock())),
                                ("embed", wagtail.embeds.blocks.EmbedBlock()),
                                (
                                    "video",
                                    cast.blocks.VideoChooserBlock(icon="media", template="cast/video/video.html"),
                                ),
                                (
                                    "audio",
                                    cast.blocks.AudioChooserBlock(icon="media", template="cast/audio/audio.html"),
                                ),
                            ]
                        ),
                    ),
                    (
                        "detail",
                        wagtail.blocks.StreamBlock(
                            [
                                ("heading", wagtail.blocks.CharBlock(form_classname="full title")),
                                ("paragraph", wagtail.blocks.RichTextBlock()),
                                ("image", wagtail.images.blocks.ImageChooserBlock(template="cast/image/image.html")),
                                ("gallery", cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock())),
                                ("embed", wagtail.embeds.blocks.EmbedBlock()),
                                (
                                    "video",
                                    cast.blocks.VideoChooserBlock(icon="media", template="cast/video/video.html"),
                                ),
                                (
                                    "audio",
                                    cast.blocks.AudioChooserBlock(icon="media", template="cast/audio/audio.html"),
                                ),
                            ]
                        ),
                    ),
                ],
                use_json_field=True,
            ),
        ),
    ]