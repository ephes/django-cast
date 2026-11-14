from collections.abc import Iterable
from typing import Any

from django.core import signing
from django.core.exceptions import ValidationError

from . import appsettings

MAX_GALLERY_IMAGES = 500
MAX_GALLERY_IDS_LENGTH = 10500
MAX_GALLERY_TOKEN_LENGTH = 16000
GALLERY_LIMIT_MESSAGE = (
    "A gallery supports at most 500 images with image IDs up to 20 characters. Split larger galleries."
)

GALLERY_MODAL_TOKEN_SALT = "cast.gallery-modal.v1"


def normalize_gallery_image_pks(image_pks: Iterable[Any]) -> list[int]:
    normalized: list[int] = []
    for pk in image_pks:
        if len(normalized) >= MAX_GALLERY_IMAGES or len(str(pk)) > 20:
            raise ValidationError(GALLERY_LIMIT_MESSAGE)
        normalized.append(int(pk))
    return normalized


def sign_gallery_image_pks(image_pks: Iterable[Any]) -> str:
    return signing.dumps(normalize_gallery_image_pks(image_pks), salt=GALLERY_MODAL_TOKEN_SALT)


def gallery_token_max_age() -> int:
    """Seconds a rendered gallery token stays valid (``CAST_GALLERY_TOKEN_MAX_AGE``, default one day)."""
    return appsettings.CAST_GALLERY_TOKEN_MAX_AGE


def gallery_image_pks_match_token(token: str, image_pks: Iterable[Any]) -> bool:
    if len(token) > MAX_GALLERY_TOKEN_LENGTH:
        return False
    try:
        signed_image_pks = signing.loads(token, salt=GALLERY_MODAL_TOKEN_SALT, max_age=gallery_token_max_age())
    except signing.BadSignature:
        return False
    return signed_image_pks == normalize_gallery_image_pks(image_pks)
