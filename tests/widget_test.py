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
    js = avc.render_js_init("id_video", "name", None)
    assert js == 'createVideoChooser("id_video");'


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
    js = avc.render_js_init("id_audio", "name", None)
    assert js == 'createAudioChooser("id_audio");'


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["audio", "video"])
def test_media_block_widget_renders_selected_and_blank(kind, request):
    from bs4 import BeautifulSoup

    from cast.blocks import AudioChooserBlock, VideoChooserBlock

    media = request.getfixturevalue(kind)
    block = {"audio": AudioChooserBlock, "video": VideoChooserBlock}[kind]()
    html = block.widget.render("media", media.pk, attrs={"id": "id_media"})
    soup = BeautifulSoup(html, "html.parser")
    assert len(soup.select('input[name="media"]')) == 1
    assert soup.select_one('input[name="media"]')["value"] == str(media.pk)
    assert soup.select_one(".title").text == media.title
    assert len(soup.select("#id_media-chooser")) == 1
    blank = BeautifulSoup(block.widget.render("media", None, attrs={"id": "id_media"}), "html.parser")
    assert blank.select_one("#id_media-chooser.blank")
    assert not blank.select_one('input[name="media"]').get("value")


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["audio", "video"])
def test_media_edit_destination_in_widget_and_telepath_state(kind, request):
    from bs4 import BeautifulSoup
    from django.urls import reverse

    from cast.blocks import AudioChooserBlock, VideoChooserBlock
    from cast.views.audio import get_audio_data
    from cast.views.video import get_video_data

    media = request.getfixturevalue(kind)
    block = {"audio": AudioChooserBlock, "video": VideoChooserBlock}[kind]()
    expected = reverse(f"cast{kind}:edit", args=[media.pk])
    state = block.get_form_state(media.pk)
    assert state["edit_url"] == expected
    assert {"audio": get_audio_data, "video": get_video_data}[kind](media)["edit_url"] == expected
    soup = BeautifulSoup(block.widget.render("media", media, attrs={"id": "id_media"}), "html.parser")
    link = soup.select_one("[data-chooser-edit-link]")
    assert link["href"] == expected
    assert not link.has_attr("hidden")


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["audio", "video"])
def test_deleted_media_recovers_streamfield_editor(kind, request, post):
    from bs4 import BeautifulSoup

    media = request.getfixturevalue(kind)
    media_id = media.pk
    post.body = [{"type": "detail", "value": [{"type": kind, "value": media_id}]}]
    post.save()
    media.delete()
    post.refresh_from_db()
    form = post.get_edit_handler().get_form_class()(instance=post)
    html = str(form["body"])
    assert "Choose" in html
    child = post.body[0].value[0]
    assert child.block.get_form_state(child.value) is None
    soup = BeautifulSoup(child.block.widget.render("media", media_id, attrs={"id": "id_media"}), "html.parser")
    assert soup.select_one("#id_media-chooser.blank")
    assert not soup.select_one('input[name="media"]').get("value")


@pytest.mark.django_db
@pytest.mark.parametrize("widget", [AdminAudioChooser, AdminVideoChooser])
def test_media_chooser_does_not_hide_invalid_ids_or_database_failures(widget, monkeypatch):
    from django.db import DatabaseError

    from cast.models import Audio, Video

    chooser = widget()
    with pytest.raises(ValueError):
        chooser.get_value_data("invalid")
    model = Audio if widget is AdminAudioChooser else Video

    def fail(**kwargs):
        raise DatabaseError("synthetic database failure")

    monkeypatch.setattr(model.objects, "get", fail)
    with pytest.raises(DatabaseError, match="synthetic"):
        chooser.get_value_data(123)
