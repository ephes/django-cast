# Generated by Django 2.0.9 on 2018-11-19 11:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("cast", "0009_blog_uuid")]

    operations = [
        migrations.AddField(
            model_name="blog",
            name="email",
            field=models.EmailField(
                blank=True, default=None, max_length=254, null=True
            ),
        )
    ]
