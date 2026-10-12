"""GPS removal for newly supplied Wagtail image files."""

from io import BytesIO
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile, File
from PIL import ExifTags, Image, ImageSequence
from wagtail.images.forms import BaseImageForm, get_image_base_form
from wagtail.utils.file import hash_filelike
from willow.image import Image as WillowImage

GPS_INFO = ExifTags.IFD.GPSInfo
GPSImageForm: Any = None


def has_gps(image: Image.Image) -> bool:
    """Inspect every frame using Pillow's public EXIF API."""
    return any(GPS_INFO in frame.getexif() for frame in ImageSequence.Iterator(image))


def sanitize_upload(upload: File) -> File:
    """Return a sanitized file, leaving GPS-free originals unchanged."""
    try:
        if WillowImage.open(upload).format_name == "svg":
            return upload
        with Image.open(upload) as image:
            if not has_gps(image):
                return upload
            if getattr(image, "n_frames", 1) > 1:
                raise ValueError(
                    "GPS-bearing multi-frame images (including multi-picture JPEGs) cannot be uploaded safely."
                )
            if image.format not in {"JPEG", "PNG", "WEBP", "AVIF", "HEIF"}:
                raise ValueError("GPS removal is not supported for this image format.")
            image.seek(0)
            exif = image.getexif()
            del exif[GPS_INFO]
            options: dict[str, Any] = {key: image.info[key] for key in ("icc_profile", "dpi") if key in image.info}
            if image.format == "JPEG":
                options["quality"] = "keep"
            output = BytesIO()
            image.save(output, format=image.format, exif=exif.tobytes(), **options)
        return ContentFile(output.getvalue(), name=upload.name)
    finally:
        upload.seek(0)


class GPSImageFormMixin(BaseImageForm):
    """Validate and sanitize before either normal or deferred upload storage."""

    def clean(self: Any) -> dict[str, Any]:
        cleaned = super().clean()
        upload = cleaned.get("file")
        if upload and "file" in self.changed_data:
            try:
                sanitized = sanitize_upload(upload)
                if sanitized is not upload:
                    # Wagtail's deferred uploader saves request.FILES, not cleaned_data.
                    # Keep the UploadedFile referenced by request.FILES and its
                    # real disk path intact for Django's storage move operation.
                    upload.seek(0)
                    upload.truncate()
                    upload.write(sanitized.read())
                    upload.flush()
                    upload.size = sanitized.size
                    upload.seek(0)
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
                self.add_error("file", ValidationError(str(exc), code="gps_metadata"))
        return cleaned


def install_upload_gps_form() -> None:
    """Wrap the site's configured image form through Wagtail's public setting."""
    global GPSImageForm
    path = "cast.image_metadata.GPSImageForm"
    if getattr(settings, "WAGTAILIMAGES_IMAGE_FORM_BASE", "") == path:
        return
    GPSImageForm = type("GPSImageForm", (GPSImageFormMixin, get_image_base_form()), {})
    settings.WAGTAILIMAGES_IMAGE_FORM_BASE = path


def strip_upload_gps(sender: type, instance: Any, **kwargs: Any) -> None:
    """Sanitize direct model uploads before Django writes them to storage."""
    if kwargs.get("raw") or not instance.file or instance.file._committed:
        return
    upload = instance.file
    content = sanitize_upload(upload)
    if content is upload:
        return
    instance.file = content
    # Wagtail forms compute these before model signals run.
    instance.file_size = content.size
    instance.file_hash = hash_filelike(content)
