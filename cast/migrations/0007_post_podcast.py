# Generated by Django 2.0.9 on 2018-11-18 13:06

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [("cast", "0006_auto_20181109_1159")]

    operations = [
        migrations.AddField(
            model_name="post",
            name="podcast",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="posts",
                to="cast.Audio",
            ),
        )
    ]
