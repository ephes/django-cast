# Generated by Django 3.2.7 on 2021-09-21 08:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cast', '0017_alter_post_body'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chaptermark',
            name='start',
            field=models.TimeField(unique=True, verbose_name='Start time of chaptermark'),
        ),
    ]
