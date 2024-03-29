# Generated by Django 5.0 on 2023-12-23 08:13

import cast.blocks
import wagtail.blocks
import wagtail.embeds.blocks
import wagtail.fields
import wagtail.images.blocks
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cast', '0052_alter_blog_template_base_dir_alter_post_body_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='post',
            name='body',
            field=wagtail.fields.StreamField([('overview', wagtail.blocks.StreamBlock([('heading', wagtail.blocks.CharBlock(form_classname='full title')), ('paragraph', wagtail.blocks.RichTextBlock()), ('code', wagtail.blocks.StructBlock([('language', wagtail.blocks.CharBlock(help_text='The language of the code block')), ('source', wagtail.blocks.TextBlock(help_text='The source code of the block', rows=8))], icon='code')), ('image', cast.blocks.CastImageChooserBlock(template='cast/image/image.html')), ('gallery', wagtail.blocks.StructBlock([('gallery', cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock())), ('layout', wagtail.blocks.ChoiceBlock(choices=[('default', 'Web Component with Modal'), ('htmx', 'HTMX based layout')]))])), ('embed', wagtail.embeds.blocks.EmbedBlock()), ('video', cast.blocks.VideoChooserBlock(icon='media', template='cast/video/video.html')), ('audio', cast.blocks.AudioChooserBlock(icon='media', template='cast/audio/audio.html'))])), ('detail', wagtail.blocks.StreamBlock([('heading', wagtail.blocks.CharBlock(form_classname='full title')), ('paragraph', wagtail.blocks.RichTextBlock()), ('code', wagtail.blocks.StructBlock([('language', wagtail.blocks.CharBlock(help_text='The language of the code block')), ('source', wagtail.blocks.TextBlock(help_text='The source code of the block', rows=8))], icon='code')), ('image', cast.blocks.CastImageChooserBlock(template='cast/image/image.html')), ('gallery', wagtail.blocks.StructBlock([('gallery', cast.blocks.GalleryBlock(wagtail.images.blocks.ImageChooserBlock())), ('layout', wagtail.blocks.ChoiceBlock(choices=[('default', 'Web Component with Modal'), ('htmx', 'HTMX based layout')]))])), ('embed', wagtail.embeds.blocks.EmbedBlock()), ('video', cast.blocks.VideoChooserBlock(icon='media', template='cast/video/video.html')), ('audio', cast.blocks.AudioChooserBlock(icon='media', template='cast/audio/audio.html'))]))], use_json_field=True),
        ),
    ]
