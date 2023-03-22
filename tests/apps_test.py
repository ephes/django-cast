from django.apps import apps


def test_delete_wagtail_images_app_setting(mocker):
    cast_config = apps.get_app_config("cast")

    # delete images True -> do not disconnect post_delete_file_cleanup
    mocker.patch("cast.appsettings.DELETE_WAGTAIL_IMAGES", True)
    mocked_disconnect = mocker.patch("cast.appsettings.post_delete.disconnect")
    cast_config.ready()
    assert mocked_disconnect.call_count == 0

    # delete images False -> disconnect post_delete_file_cleanup
    mocker.patch("cast.appsettings.DELETE_WAGTAIL_IMAGES", False)
    mocked_disconnect = mocker.patch("cast.appsettings.post_delete.disconnect")
    cast_config.ready()
    assert mocked_disconnect.call_count == 1
