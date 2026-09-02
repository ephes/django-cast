import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from cast.forms import AudioForm, VideoForm
from cast.media_derivation import save_audio_with_derivations, save_video_with_derivations
from cast.media_validation import validate_audio_upload, validate_video_upload
from cast.models import Audio, Video


pytestmark = pytest.mark.django_db


MP4_HEADER = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
MOV_HEADER = b"\x00\x00\x00\x14moov\x00\x00\x00\x00qt  "
AVI_HEADER = b"RIFF\x24\x00\x00\x00AVI LIST"
OGG_HEADER = b"OggS\x00\x02\x00\x00\x00\x00"
MP3_HEADER = b"ID3\x04\x00\x00\x00\x00\x00\x15"


def upload(name: str, content: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name=name, content=content, content_type=content_type)


def test_validate_upload_helpers_accept_none():
    validate_audio_upload(None, audio_format="m4a")
    validate_video_upload(None)


def test_validate_audio_upload_accepts_seekable_file_without_size():
    class SeekableUpload:
        name = "clip.m4a"
        content_type = "audio/mp4"

        def __init__(self):
            self.content = bytearray(MP4_HEADER)
            self.position = 0

        def read(self, size=-1):
            if size < 0:
                size = len(self.content) - self.position
            end = min(self.position + size, len(self.content))
            chunk = bytes(self.content[self.position : end])
            self.position = end
            return chunk

        def seek(self, offset, whence=0):
            if whence == 0:
                self.position = offset
            elif whence == 2:
                self.position = len(self.content) + offset
            else:
                self.position += offset

        def tell(self):
            return self.position

    validate_audio_upload(SeekableUpload(), audio_format="m4a")


def test_validate_audio_upload_accepts_stream_without_tell():
    class NoTellUpload:
        name = "clip.m4a"
        content_type = "audio/mp4"

        def read(self, size=-1):
            return MP4_HEADER if size < 0 else MP4_HEADER[:size]

    validate_audio_upload(NoTellUpload(), audio_format="m4a")


def test_audio_form_accepts_valid_m4a_upload():
    form = AudioForm({}, {"m4a": upload("clip.m4a", MP4_HEADER, "audio/mp4")})

    assert form.is_valid()


def test_audio_form_accepts_valid_mp3_upload():
    form = AudioForm({}, {"mp3": upload("clip.mp3", MP3_HEADER, "audio/mpeg")})

    assert form.is_valid()


def test_audio_form_accepts_valid_oga_upload():
    form = AudioForm({}, {"oga": upload("clip.oga", OGG_HEADER, "audio/ogg")})

    assert form.is_valid()


def test_audio_form_accepts_valid_opus_upload():
    form = AudioForm({}, {"opus": upload("clip.opus", OGG_HEADER, "audio/opus")})

    assert form.is_valid()


def test_audio_form_rejects_invalid_extension():
    form = AudioForm({}, {"m4a": upload("clip.txt", MP4_HEADER, "audio/mp4")})

    assert not form.is_valid()
    assert "extension" in form.errors["m4a"][0]


def test_audio_form_rejects_invalid_magic_bytes():
    form = AudioForm({}, {"m4a": upload("clip.m4a", b"not a media file", "audio/mp4")})

    assert not form.is_valid()
    assert "supported media container" in form.errors["m4a"][0]


def test_audio_form_rejects_invalid_content_type():
    form = AudioForm({}, {"m4a": upload("clip.m4a", MP4_HEADER, "text/plain")})

    assert not form.is_valid()
    assert "unsupported content type" in form.errors["m4a"][0]


def test_audio_form_rejects_oversized_upload(settings):
    settings.CAST_AUDIO_UPLOAD_MAX_BYTES = len(MP3_HEADER) - 1
    form = AudioForm({}, {"mp3": upload("clip.mp3", MP3_HEADER, "audio/mpeg")})

    assert not form.is_valid()
    assert "too large" in form.errors["mp3"][0]


def test_video_form_accepts_valid_mp4_upload():
    form = VideoForm({}, {"original": upload("clip.mp4", MP4_HEADER, "video/mp4")})

    assert form.is_valid()


def test_video_form_accepts_valid_mov_upload():
    form = VideoForm({}, {"original": upload("clip.mov", MOV_HEADER, "video/quicktime")})

    assert form.is_valid()


def test_video_form_accepts_valid_m4v_upload():
    form = VideoForm({}, {"original": upload("clip.m4v", MP4_HEADER, "video/x-m4v")})

    assert form.is_valid()


def test_video_form_accepts_valid_avi_upload():
    form = VideoForm({}, {"original": upload("clip.avi", AVI_HEADER, "video/x-msvideo")})

    assert form.is_valid()


def test_video_form_rejects_invalid_extension():
    form = VideoForm({}, {"original": upload("clip.txt", MP4_HEADER, "video/mp4")})

    assert not form.is_valid()
    assert "extension" in form.errors["original"][0]


def test_video_form_rejects_invalid_magic_bytes():
    form = VideoForm({}, {"original": upload("clip.mp4", b"not a media file", "video/mp4")})

    assert not form.is_valid()
    assert "supported media container" in form.errors["original"][0]


def test_video_form_rejects_invalid_content_type():
    form = VideoForm({}, {"original": upload("clip.mp4", MP4_HEADER, "text/plain")})

    assert not form.is_valid()
    assert "unsupported content type" in form.errors["original"][0]


def test_video_form_rejects_oversized_upload(settings):
    settings.CAST_VIDEO_UPLOAD_MAX_BYTES = len(MP4_HEADER) - 1
    form = VideoForm({}, {"original": upload("clip.mp4", MP4_HEADER, "video/mp4")})

    assert not form.is_valid()
    assert "too large" in form.errors["original"][0]


@pytest.mark.django_db
def test_audio_save_rejects_invalid_upload_before_ffprobe(user, mocker):
    get_duration = mocker.patch("cast.models.audio.Audio._get_audio_duration")
    audio = Audio(user=user, m4a=upload("clip.m4a", b"not a media file", "audio/mp4"))

    with pytest.raises(ValidationError):
        save_audio_with_derivations(audio)

    get_duration.assert_not_called()
    assert Audio.objects.count() == 0


@pytest.mark.django_db
def test_video_save_rejects_invalid_upload_before_ffmpeg(user, mocker):
    create_poster = mocker.patch("cast.models.video.Video._create_poster")
    video = Video(user=user, title="clip", original=upload("clip.mp4", b"not a media file", "video/mp4"))

    with pytest.raises(ValidationError):
        save_video_with_derivations(video)

    create_poster.assert_not_called()
    assert Video.objects.count() == 0


@pytest.mark.django_db
def test_api_video_upload_rejects_invalid_media_before_poster(client, user, mocker):
    create_poster = mocker.patch("cast.models.video.Video._create_poster")
    client.login(username=user.username, password=user._password)

    response = client.post(
        reverse("cast:api:upload_video"),
        {"original": upload("clip.mp4", b"not a media file", "video/mp4")},
    )

    assert response.status_code == 400
    create_poster.assert_not_called()
    assert Video.objects.count() == 0
