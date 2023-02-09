import pytest

from cast.widgets import AdminAudioChooser, AdminVideoChooser


@pytest.mark.django_db
def test_video_chooser_get_value_data_value_not_none(video):
    avc = AdminVideoChooser()

    # get video data by passing the primary key
    data = avc.get_value_data(video.pk)
    assert data["id"] == video.pk

    # get video data by passing the video object
    data = avc.get_value_data(video)
    assert data["id"] == video.pk


def test_video_chooser_render_js_init():
    avc = AdminVideoChooser()
    js = avc.render_js_init(1, "name", None)
    assert js == "createVideoChooser(1);"


@pytest.mark.django_db
def test_audio_chooser_get_value_data_value_not_none(audio):
    avc = AdminAudioChooser()

    # get audio data by passing the primary key
    data = avc.get_value_data(audio.pk)
    assert data["id"] == audio.pk

    # get audio data by passing the audio object
    data = avc.get_value_data(audio)
    assert data["id"] == audio.pk


def test_audio_chooser_render_js_init():
    avc = AdminAudioChooser()
    js = avc.render_js_init(1, "name", None)
    assert js == "createAudioChooser(1);"
