# Generated by Django 3.2.5 on 2021-07-22 09:47

import cast.blocks
from django.db import migrations
import wagtail.core.blocks
import wagtail.core.fields
import wagtail.embeds.blocks
import wagtail.images.blocks


class Migration(migrations.Migration):

    dependencies = [
        ('cast', '0008_auto_20210712_0919'),
    ]

    operations = [
        migrations.AlterField(
            model_name='post',
            name='body',
            field=wagtail.core.fields.StreamField([('heading', wagtail.core.blocks.CharBlock(form_classname='full title')), ('paragraph', wagtail.core.blocks.RichTextBlock()), ('image', wagtail.images.blocks.ImageChooserBlock(template='cast/wagtail_image.html')), ('gallery', cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock())), ('embed', wagtail.embeds.blocks.EmbedBlock()), ('video', cast.blocks.VideoChooserBlock(icon='media', template='cast/wagtail_video.html'))]),
        ),
    ]
