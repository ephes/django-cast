from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from wagtail.blocks import RichTextBlock
from wagtail.images import get_image_model
from wagtail.images.permissions import permission_policy as image_permission_policy

from .errors import EditorValidationError

SUPPORTED_OVERVIEW_BLOCKS = frozenset({"heading", "paragraph", "code", "image", "gallery", "audio"})

# A single shared RichTextBlock used to validate/normalize paragraph HTML through
# the same path Wagtail uses on admin save.
_PARAGRAPH_BLOCK = RichTextBlock()


def _choosable(obj_id: Any, user: Any, *, queryset: Any, policy: Any) -> bool:
    """True if ``obj_id`` exists in ``queryset`` and ``user`` may ``choose`` it.

    Existence and visibility are deliberately collapsed into one boolean so callers report a single
    ``not_found`` and never leak the existence of media the caller cannot access.
    """
    if not isinstance(obj_id, int) or isinstance(obj_id, bool):
        return False
    obj = queryset.filter(pk=obj_id).first()
    if obj is None:
        return False
    return policy.user_has_permission_for_instance(user, "choose", obj)


def image_choosable_by(image_id: Any, user: Any) -> bool:
    """True if the image exists and the caller may choose it (Wagtail image ``choose`` permission)."""
    return _choosable(image_id, user, queryset=get_image_model().objects, policy=image_permission_policy)


def audio_choosable_by(audio_id: Any, user: Any) -> bool:
    """True if the cast audio exists and the caller may choose it.

    Audio has no dedicated ``choose_audio`` permission, so this uses the same collection-ownership
    policy the audio chooser is built on: superusers and users with audio collection permissions pass.
    """
    from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy

    from ...models import Audio

    policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")
    return _choosable(audio_id, user, queryset=Audio.objects, policy=policy)


def author_blocks_to_overview(blocks: list[dict], *, user: Any, path_prefix: str = "overview") -> list[dict]:
    """Convert an author-facing block list into a Wagtail ``overview`` StreamField value.

    ``user`` is required: referenced images are validated for both existence and the caller's Wagtail
    ``choose`` permission, so a client cannot attach images it could not select in the Wagtail admin.

    Raises :class:`EditorValidationError` aggregating every problem with a field-precise path.
    """
    errors: dict[str, list[dict[str, str]]] = {}
    result: list[dict] = []

    if not isinstance(blocks, list):
        raise EditorValidationError(
            {path_prefix: [{"code": "invalid", "message": "overview must be a list of blocks."}]}
        )

    for index, block in enumerate(blocks):
        base = f"{path_prefix}.{index}"
        if not isinstance(block, dict) or "type" not in block:
            errors[f"{base}.type"] = [{"code": "required", "message": "Each block needs a 'type'."}]
            continue
        block_type = block.get("type")
        value = block.get("value")

        if block_type not in SUPPORTED_OVERVIEW_BLOCKS:
            errors[f"{base}.type"] = [
                {"code": "unsupported_block_type", "message": f"Block type {block_type!r} is not supported."}
            ]
            continue

        if block_type == "heading":
            if not isinstance(value, str):
                errors[f"{base}.value"] = [{"code": "invalid", "message": "Expected a string value."}]
                continue
            result.append({"type": "heading", "value": value})

        elif block_type == "paragraph":
            if not isinstance(value, str):
                errors[f"{base}.value"] = [{"code": "invalid", "message": "Expected a string value."}]
                continue
            # Validate/normalize the rich text through Wagtail's block clean path,
            # the same path the admin uses on save.
            try:
                cleaned = _PARAGRAPH_BLOCK.clean(_PARAGRAPH_BLOCK.to_python(value))
            except DjangoValidationError as exc:
                message = "; ".join(exc.messages) or "Invalid rich text."
                errors[f"{base}.value"] = [{"code": "invalid", "message": message}]
                continue
            result.append({"type": "paragraph", "value": _PARAGRAPH_BLOCK.get_prep_value(cleaned)})

        elif block_type == "code":
            if not isinstance(value, dict):
                errors[f"{base}.value"] = [{"code": "invalid", "message": "Expected an object value."}]
                continue
            block_errors = False
            for key in ("language", "source"):
                if not isinstance(value.get(key), str) or not value.get(key):
                    errors[f"{base}.value.{key}"] = [
                        {"code": "required", "message": f"Code block '{key}' is required."}
                    ]
                    block_errors = True
            if block_errors:
                continue
            result.append({"type": "code", "value": {"language": value["language"], "source": value["source"]}})

        elif block_type == "image":
            image_id = value.get("id") if isinstance(value, dict) else None
            if not image_choosable_by(image_id, user):
                errors[f"{base}.value.id"] = [
                    {"code": "not_found", "message": f"Image {image_id} does not exist or is not accessible."}
                ]
                continue
            result.append({"type": "image", "value": image_id})

        elif block_type == "gallery":
            if not isinstance(value, list) or not value:
                errors[f"{base}.value"] = [
                    {"code": "invalid", "message": "Gallery value must be a non-empty list of image refs."}
                ]
                continue
            items = []
            gallery_ok = True
            for img_index, ref in enumerate(value):
                image_id = ref.get("id") if isinstance(ref, dict) else None
                if not image_choosable_by(image_id, user):
                    errors[f"{base}.value.{img_index}.id"] = [
                        {"code": "not_found", "message": f"Image {image_id} does not exist or is not accessible."}
                    ]
                    gallery_ok = False
                    continue
                items.append({"id": str(uuid.uuid4()), "type": "item", "value": image_id})
            if not gallery_ok:
                continue
            result.append({"type": "gallery", "value": {"layout": "default", "gallery": items}})

        else:  # block_type == "audio" (the only remaining supported type)
            audio_id = value.get("id") if isinstance(value, dict) else None
            if not audio_choosable_by(audio_id, user):
                errors[f"{base}.value.id"] = [
                    {"code": "not_found", "message": f"Audio {audio_id} does not exist or is not accessible."}
                ]
                continue
            result.append({"type": "audio", "value": audio_id})

    if errors:
        raise EditorValidationError(errors)
    return result


def overview_to_author_blocks(overview_value: list[dict]) -> list[dict]:
    """Inverse of :func:`author_blocks_to_overview` for supported block types."""
    author: list[dict] = []
    for block in overview_value:
        block_type = block.get("type")
        value = block.get("value")
        if block_type in ("heading", "paragraph"):
            author.append({"type": block_type, "value": value})
        elif block_type == "code" and isinstance(value, dict):
            author.append({"type": "code", "value": {"language": value["language"], "source": value["source"]}})
        elif block_type == "image":
            author.append({"type": "image", "value": {"id": value}})
        elif block_type == "audio":
            author.append({"type": "audio", "value": {"id": value}})
        elif block_type == "gallery":
            items = value.get("gallery", []) if isinstance(value, dict) else []
            author.append({"type": "gallery", "value": [{"id": item["value"]} for item in items]})
        # unknown/unsupported stored blocks are skipped in this slice
    return author
