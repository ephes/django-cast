from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("threadedcomments", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CastComment",
            fields=[],
            options={
                "verbose_name": "Comment",
                "verbose_name_plural": "Comments",
                "managed": False,
                "proxy": True,
            },
            bases=("threadedcomments.threadedcomment",),
        ),
    ]
