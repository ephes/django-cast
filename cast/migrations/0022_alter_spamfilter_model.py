# Generated by Django 3.2.8 on 2021-10-05 09:29

import cast.models.moderation
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cast', '0021_spamfilter'),
    ]

    operations = [
        migrations.AlterField(
            model_name='spamfilter',
            name='model',
            field=models.JSONField(default=dict, encoder=cast.models.moderation.ModelEncoder, verbose_name='Spamfilter Model'),
        ),
    ]