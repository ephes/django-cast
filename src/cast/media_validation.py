from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


DEFAULT_AUDIO_UPLOAD_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_VIDEO_UPLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024
GENERIC_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream"}
QUICKTIME_TOP_LEVEL_ATOMS = {b"free", b"mdat", b"moov", b"wide"}


@dataclass(frozen=True)
class MediaUploadSpec:
    extensions: frozenset[str]
    content_types: frozenset[str]
    header_matches: Callable[[bytes], bool]


def _looks_like_mp4(header: bytes) -> bool:
    return len(header) >= 12 and header[4:8] == b"ftyp"


def _looks_like_quicktime(header: bytes) -> bool:
    return len(header) >= 8 and header[4:8] in QUICKTIME_TOP_LEVEL_ATOMS


def _looks_like_mp3(header: bytes) -> bool:
    return header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)


def _looks_like_ogg(header: bytes) -> bool:
    return header.startswith(b"OggS")


def _looks_like_avi(header: bytes) -> bool:
    return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI "


AUDIO_UPLOAD_SPECS: dict[str, MediaUploadSpec] = {
    "m4a": MediaUploadSpec(
        extensions=frozenset({"m4a"}),
        content_types=frozenset({"audio/mp4", "audio/m4a", "audio/x-m4a"}),
        header_matches=_looks_like_mp4,
    ),
    "mp3": MediaUploadSpec(
        extensions=frozenset({"mp3"}),
        content_types=frozenset({"audio/mpeg", "audio/mp3", "audio/x-mpeg"}),
        header_matches=_looks_like_mp3,
    ),
    "oga": MediaUploadSpec(
        extensions=frozenset({"oga", "ogg"}),
        content_types=frozenset({"audio/ogg", "application/ogg"}),
        header_matches=_looks_like_ogg,
    ),
    "opus": MediaUploadSpec(
        extensions=frozenset({"opus"}),
        content_types=frozenset({"audio/ogg", "audio/opus", "application/ogg"}),
        header_matches=_looks_like_ogg,
    ),
}

VIDEO_UPLOAD_SPEC = MediaUploadSpec(
    extensions=frozenset({"avi", "m4v", "mov", "mp4"}),
    content_types=frozenset({"video/mp4", "video/quicktime", "video/x-m4v", "video/x-msvideo"}),
    header_matches=lambda header: _looks_like_mp4(header) or _looks_like_quicktime(header) or _looks_like_avi(header),
)


def validate_audio_upload(uploaded_file: BinaryIO | None, *, audio_format: str) -> None:
    if uploaded_file is None:
        return
    spec = AUDIO_UPLOAD_SPECS[audio_format]
    validate_media_upload(
        uploaded_file,
        spec=spec,
        max_bytes=int(getattr(settings, "CAST_AUDIO_UPLOAD_MAX_BYTES", DEFAULT_AUDIO_UPLOAD_MAX_BYTES)),
        media_label=f"{audio_format.upper()} audio",
    )


def validate_video_upload(uploaded_file: BinaryIO | None) -> None:
    if uploaded_file is None:
        return
    validate_media_upload(
        uploaded_file,
        spec=VIDEO_UPLOAD_SPEC,
        max_bytes=int(getattr(settings, "CAST_VIDEO_UPLOAD_MAX_BYTES", DEFAULT_VIDEO_UPLOAD_MAX_BYTES)),
        media_label="Video",
    )


def validate_media_upload(
    uploaded_file: BinaryIO,
    *,
    spec: MediaUploadSpec,
    max_bytes: int,
    media_label: str,
) -> None:
    name = getattr(uploaded_file, "name", "") or ""
    extension = Path(name).suffix.lower().lstrip(".")
    if extension not in spec.extensions:
        raise ValidationError(
            _("%(label)s files must use one of these extensions: %(extensions)s."),
            code="invalid_extension",
            params={"label": media_label, "extensions": ", ".join(sorted(spec.extensions))},
        )

    size = _get_uploaded_file_size(uploaded_file)
    if size is not None and size > max_bytes:
        raise ValidationError(
            _("%(label)s file is too large. The maximum allowed size is %(max_size)s bytes."),
            code="file_too_large",
            params={"label": media_label, "max_size": max_bytes},
        )

    content_type = str(getattr(uploaded_file, "content_type", "") or "").split(";", 1)[0].strip().lower()
    if content_type and content_type not in spec.content_types and content_type not in GENERIC_CONTENT_TYPES:
        raise ValidationError(
            _("%(label)s file has unsupported content type %(content_type)s."),
            code="invalid_content_type",
            params={"label": media_label, "content_type": content_type},
        )

    header = _read_header(uploaded_file)
    if not spec.header_matches(header):
        raise ValidationError(
            _("%(label)s file does not look like a supported media container."),
            code="invalid_media_container",
            params={"label": media_label},
        )


def _read_header(uploaded_file: BinaryIO, size: int = 64) -> bytes:
    position = _safe_tell(uploaded_file)
    if position is not None:
        uploaded_file.seek(0)
    header = uploaded_file.read(size)
    if position is not None:
        uploaded_file.seek(0)
    return header


def _get_uploaded_file_size(uploaded_file: BinaryIO) -> int | None:
    size = getattr(uploaded_file, "size", None)
    if isinstance(size, int):
        return size

    position = _safe_tell(uploaded_file)
    if position is None:
        return None
    try:
        uploaded_file.seek(0, 2)
        return uploaded_file.tell()
    finally:
        uploaded_file.seek(position)


def _safe_tell(uploaded_file: BinaryIO) -> int | None:
    try:
        return uploaded_file.tell()
    except (AttributeError, OSError):
        return None
