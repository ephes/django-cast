from collections.abc import Iterable
from typing import Any

from django.core import signing

from . import appsettings

GALLERY_MODAL_TOKEN_SALT = "cast.gallery-modal.v1"


def normalize_gallery_image_pks(image_pks: Iterable[Any]) -> list[int]:
    return [int(pk) for pk in image_pks]


def sign_gallery_image_pks(image_pks: Iterable[Any]) -> str:
    return signing.dumps(normalize_gallery_image_pks(image_pks), salt=GALLERY_MODAL_TOKEN_SALT)


def gallery_token_max_age() -> int:
    """Seconds a rendered gallery token stays valid (``CAST_GALLERY_TOKEN_MAX_AGE``, default one day)."""
    return appsettings.CAST_GALLERY_TOKEN_MAX_AGE


def gallery_image_pks_match_token(token: str, image_pks: Iterable[Any]) -> bool:
    try:
        signed_image_pks = signing.loads(token, salt=GALLERY_MODAL_TOKEN_SALT, max_age=gallery_token_max_age())
    except signing.BadSignature:
        return False
    return signed_image_pks == normalize_gallery_image_pks(image_pks)
