# Generated by Django 3.0.5 on 2020-04-12 15:32

import cast.blocks
from django.db import migrations
import wagtail.core.blocks
import wagtail.core.fields
import wagtail.images.blocks


class Migration(migrations.Migration):

    dependencies = [
        ('cast', '0031_remove_blogpage_intro'),
    ]

    operations = [
        migrations.AlterField(
            model_name='blogpage',
            name='body',
            field=wagtail.core.fields.StreamField([('heading', wagtail.core.blocks.CharBlock(classname='full title')), ('paragraph', wagtail.core.blocks.RichTextBlock()), ('image', wagtail.images.blocks.ImageChooserBlock(template='cast/wagtail_image.html')), ('gallery', cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock(), template='cast/wagtail_gallery_block.html'))]),
        ),
    ]
