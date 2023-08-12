from django.core.management import call_command


def test_media_backup_without_storages(capsys, settings):
    settings.STORAGES = {}
    call_command("media_backup")
    captured = capsys.readouterr()
    assert captured.out == "production or backup storage not configured\n"


def test_media_backup_without_django_version(capsys, settings, mocker):
    settings.STORAGES = {}
    mocker.patch("cast.management.commands.media_backup.DJANGO_VERSION_VALID", False)
    call_command("media_backup")
    captured = capsys.readouterr()
    assert captured.out == "Django version >= 4.2 is required\n"
