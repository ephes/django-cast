"""Shared test data and setup helpers."""

from django.core.files.uploadedfile import SimpleUploadedFile

OGG_CONTENT = b"OggS\x00\x02\x00\x00\x00\x00" + b"\x00" * 64


def oga_upload(name: str = "episode.oga") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, OGG_CONTENT, content_type="audio/ogg")
