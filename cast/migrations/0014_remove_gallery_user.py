# Generated by Django 3.2.6 on 2021-08-20 11:48

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('cast', '0013_alter_gallery_images'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='gallery',
            name='user',
        ),
    ]
