import pytest
from django.core.files.uploadedfile import SimpleUploadedFile


def create_minimal_mp3():
    mp3 = (
        b"\xff\xe3\x18\xc4\x00\x00\x00\x03H\x00\x00\x00\x00"
        b"LAME3.98.2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    return mp3


@pytest.fixture()
def mp3_audio():
    mp3 = create_minimal_mp3()
    simple_mp3 = SimpleUploadedFile(name="test.mp3", content=mp3, content_type="audio/mpeg")
    return simple_mp3


@pytest.fixture()
def superuser(django_user_model):
    """A superuser, which passes every Wagtail page and image ``choose`` permission."""
    return django_user_model.objects.create_superuser(
        username="editor-su", email="editor-su@example.com", password="password"
    )
