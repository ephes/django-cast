from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("cast", "0075_podcast_automatic_episode_numbering_enabled_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="audio",
            options={
                "ordering": ("-created",),
                "permissions": (("choose_audio", "Can choose audio"),),
            },
        ),
        migrations.AlterModelOptions(
            name="transcript",
            options={
                "ordering": ("-id",),
                "permissions": (("choose_transcript", "Can choose transcript"),),
            },
        ),
        migrations.AlterModelOptions(
            name="video",
            options={
                "permissions": (("choose_video", "Can choose video"),),
            },
        ),
    ]
