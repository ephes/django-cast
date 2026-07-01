from collections.abc import Iterable
from typing import Any

from django.core import signing

GALLERY_MODAL_TOKEN_SALT = "cast.gallery-modal.v1"


def normalize_gallery_image_pks(image_pks: Iterable[Any]) -> list[int]:
    return [int(pk) for pk in image_pks]


def sign_gallery_image_pks(image_pks: Iterable[Any]) -> str:
    return signing.dumps(normalize_gallery_image_pks(image_pks), salt=GALLERY_MODAL_TOKEN_SALT)


def gallery_image_pks_match_token(token: str, image_pks: Iterable[Any]) -> bool:
    try:
        signed_image_pks = signing.loads(token, salt=GALLERY_MODAL_TOKEN_SALT)
    except signing.BadSignature:
        return False
    return signed_image_pks == normalize_gallery_image_pks(image_pks)
