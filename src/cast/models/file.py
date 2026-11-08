from pathlib import PurePosixPath

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files import File as DjangoFile
from django.db import models
from model_utils.models import TimeStampedModel

from .. import appsettings


def allowed_file_extensions() -> set[str]:
    """Return the lower-case extensions accepted for generic ``File`` uploads."""
    return {
        extension.strip().lower().lstrip(".")
        for extension in appsettings.CAST_FILE_EXTENSIONS
        if isinstance(extension, str) and extension.strip()
    }


def validate_file_extension(value: DjangoFile) -> None:
    """Reject generic uploads whose extension is not in ``CAST_FILE_EXTENSIONS``.

    Active content such as HTML, SVG, XML or JavaScript would otherwise be stored
    at a predictable media URL and could execute as same-origin script.
    """
    name = PurePosixPath(str(getattr(value, "name", "") or "")).name
    extension = PurePosixPath(name).suffix.lower().lstrip(".")
    allowed = allowed_file_extensions()
    if not extension or extension not in allowed:
        raise ValidationError(
            "File extension \u201c%(extension)s\u201d is not allowed. Allowed extensions are: %(allowed)s.",
            code="invalid_extension",
            params={"extension": extension, "allowed": ", ".join(sorted(allowed))},
        )


class File(TimeStampedModel):
    """A generic uploaded file associated with a user.

    Used for documents and other file types that are not images, audio, or video.
    Only extensions from ``CAST_FILE_EXTENSIONS`` are accepted.
    """

    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    original = models.FileField(upload_to="cast_files/", validators=[validate_file_extension])

    def get_all_paths(self) -> set[str]:
        paths = set()
        if self.original.name:
            paths.add(self.original.name)
        return paths
