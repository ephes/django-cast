from django.core.management import call_command


def test_media_backup_without_storages(capsys, settings):
    settings.STORAGES = {}
    call_command("media_backup")
    captured = capsys.readouterr()
    assert captured.out == "production or backup storage not configured\n"
