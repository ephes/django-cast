from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from wagtail.blocks import RichTextBlock
from wagtail.images import get_image_model
from wagtail.images.permissions import permission_policy as image_permission_policy

from .errors import EditorValidationError

SUPPORTED_BODY_BLOCKS = frozenset({"heading", "paragraph", "code", "image", "gallery", "audio", "video"})
SUPPORTED_OVERVIEW_BLOCKS = SUPPORTED_BODY_BLOCKS

# A single shared RichTextBlock used to validate/normalize paragraph HTML through
# the same path Wagtail uses on admin save.
_PARAGRAPH_BLOCK = RichTextBlock()


def get_choosable_object(obj_id: Any, user: Any, *, queryset: Any, policy: Any) -> Any | None:
    """Return an object when ``user`` may ``choose`` it, otherwise ``None``.

    Existence and visibility are deliberately collapsed into ``None`` so callers report a single
    ``not_found`` and never leak the existence of media the caller cannot access.
    """
    if not isinstance(obj_id, int) or isinstance(obj_id, bool):
        return None
    visible = policy.instances_user_has_permission_for(user, "choose")
    obj = queryset.filter(pk=obj_id, pk__in=visible.values("pk")).first()
    if obj is None:
        return None
    return obj


def get_choosable_image(image_id: Any, user: Any) -> Any | None:
    """Return the image when it exists and the caller may choose it."""
    return get_choosable_object(image_id, user, queryset=get_image_model().objects, policy=image_permission_policy)


def image_choosable_by(image_id: Any, user: Any) -> bool:
    """True if the image exists and the caller may choose it (Wagtail image ``choose`` permission)."""
    return get_choosable_image(image_id, user) is not None


def get_choosable_audio(audio_id: Any, user: Any) -> Any | None:
    """Return the audio when it exists and the caller may choose it."""
    from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy

    from ...models import Audio

    policy = CollectionOwnershipPermissionPolicy(Audio, auth_model=Audio, owner_field_name="user")
    return get_choosable_object(audio_id, user, queryset=Audio.objects, policy=policy)


def audio_choosable_by(audio_id: Any, user: Any) -> bool:
    """True if the cast audio exists and the caller may choose it.

    Audio has no dedicated ``choose_audio`` permission, so this uses the same collection-ownership
    policy the audio chooser is built on: superusers and users with audio collection permissions pass.
    """
    return get_choosable_audio(audio_id, user) is not None


def get_choosable_video(video_id: Any, user: Any) -> Any | None:
    """Return the video when it exists and the caller may choose it."""
    from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy

    from ...models import Video

    policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")
    return get_choosable_object(video_id, user, queryset=Video.objects, policy=policy)


def video_choosable_by(video_id: Any, user: Any) -> bool:
    """True if the cast video exists and the caller may choose it."""
    return get_choosable_video(video_id, user) is not None


def _preserved_unsupported_block(
    value: Any, *, existing_section: list[dict] | None, base: str, path_prefix: str
) -> tuple[dict | None, int | None, dict[str, list[dict[str, str]]]]:
    if existing_section is None:
        return (
            None,
            None,
            {
                f"{base}.type": [
                    {"code": "unsupported_block_type", "message": "Block type 'unsupported' is not supported."}
                ]
            },
        )
    if not isinstance(value, dict):
        return None, None, {f"{base}.value": [{"code": "invalid", "message": "Expected an object value."}]}
    stored_type = value.get("stored_type")
    position = value.get("position")
    if not isinstance(stored_type, str) or not isinstance(position, str):
        return (
            None,
            None,
            {
                f"{base}.value": [
                    {"code": "invalid", "message": "Unsupported placeholders need stored_type and position."}
                ]
            },
        )
    prefix = f"{path_prefix}."
    try:
        existing_index = int(position.removeprefix(prefix))
    except ValueError:
        existing_index = -1
    if not position.startswith(prefix) or existing_index < 0 or existing_index >= len(existing_section):
        return (
            None,
            None,
            {
                f"{base}.value.position": [
                    {"code": "invalid", "message": "Unsupported placeholder position does not match a stored block."}
                ]
            },
        )
    existing_block = existing_section[existing_index]
    if existing_block.get("type") != stored_type:
        return (
            None,
            None,
            {
                f"{base}.value.stored_type": [
                    {"code": "invalid", "message": "Unsupported placeholder does not match the stored block."}
                ]
            },
        )
    return dict(existing_block), existing_index, {}


def author_blocks_to_section(
    blocks: list[dict], *, user: Any, path_prefix: str, existing_section: list[dict] | None = None
) -> list[dict]:
    """Convert an author-facing block list into a Wagtail body-section StreamField value.

    ``user`` is required: referenced images are validated for both existence and the caller's Wagtail
    ``choose`` permission, so a client cannot attach images it could not select in the Wagtail admin.

    Raises :class:`EditorValidationError` aggregating every problem with a field-precise path.
    """
    errors: dict[str, list[dict[str, str]]] = {}
    result: list[dict] = []
    preserved_unsupported_indexes: set[int] = set()

    if not isinstance(blocks, list):
        raise EditorValidationError(
            {path_prefix: [{"code": "invalid", "message": f"{path_prefix} must be a list of blocks."}]}
        )

    for index, block in enumerate(blocks):
        base = f"{path_prefix}.{index}"
        if not isinstance(block, dict) or "type" not in block:
            errors[f"{base}.type"] = [{"code": "required", "message": "Each block needs a 'type'."}]
            continue
        block_type = block.get("type")
        value = block.get("value")

        if block_type == "unsupported":
            preserved, existing_index, placeholder_errors = _preserved_unsupported_block(
                value, existing_section=existing_section, base=base, path_prefix=path_prefix
            )
            if placeholder_errors:
                errors.update(placeholder_errors)
                continue
            assert existing_index is not None
            if existing_index in preserved_unsupported_indexes:
                errors[f"{base}.value.position"] = [
                    {"code": "duplicate", "message": "Unsupported placeholder position is already preserved."}
                ]
                continue
            preserved_unsupported_indexes.add(existing_index)
            assert preserved is not None
            result.append(preserved)
            continue

        elif block_type not in SUPPORTED_BODY_BLOCKS:
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

        elif block_type == "audio":
            audio_id = value.get("id") if isinstance(value, dict) else None
            if not audio_choosable_by(audio_id, user):
                errors[f"{base}.value.id"] = [{"code": "not_found", "message": "Referenced media is not available."}]
                continue
            result.append({"type": "audio", "value": audio_id})

        else:  # block_type == "video"
            video_id = value.get("id") if isinstance(value, dict) else None
            if not video_choosable_by(video_id, user):
                errors[f"{base}.value.id"] = [{"code": "not_found", "message": "Referenced media is not available."}]
                continue
            result.append({"type": "video", "value": video_id})

    if errors:
        raise EditorValidationError(errors)
    return result


def author_blocks_to_overview(
    blocks: list[dict], *, user: Any, path_prefix: str = "overview", existing_section: list[dict] | None = None
) -> list[dict]:
    """Backward-compatible wrapper for overview conversion."""
    return author_blocks_to_section(blocks, user=user, path_prefix=path_prefix, existing_section=existing_section)


def _unsupported_placeholder(block_type: Any, *, path_prefix: str, index: int) -> dict:
    return {"type": "unsupported", "value": {"stored_type": block_type, "position": f"{path_prefix}.{index}"}}


def _media_ref_is_available(block_type: str, value: Any, user: Any) -> bool:
    if block_type == "image":
        return image_choosable_by(value, user)
    if block_type == "audio":
        return audio_choosable_by(value, user)
    if block_type == "video":
        return video_choosable_by(value, user)
    raise ValueError(f"Unsupported media block type: {block_type}")


def section_to_author_blocks(
    section_value: list[dict], *, path_prefix: str = "overview", user: Any | None = None
) -> list[dict]:
    """Inverse of :func:`author_blocks_to_section` for supported block types."""
    author: list[dict] = []
    for index, block in enumerate(section_value):
        block_type = block.get("type")
        value = block.get("value")
        if block_type in ("heading", "paragraph"):
            author.append({"type": block_type, "value": value})
        elif block_type == "code":
            if (
                isinstance(value, dict)
                and isinstance(value.get("language"), str)
                and isinstance(value.get("source"), str)
            ):
                author.append({"type": "code", "value": {"language": value["language"], "source": value["source"]}})
            else:
                author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
        elif block_type in ("image", "audio", "video"):
            if user is not None and not _media_ref_is_available(block_type, value, user):
                author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
            else:
                author.append({"type": block_type, "value": {"id": value}})
        elif block_type == "gallery":
            items = value.get("gallery", []) if isinstance(value, dict) else []
            if (
                isinstance(items, list)
                and len(items) > 0
                and all(isinstance(item, dict) and "value" in item for item in items)
                and (
                    user is None
                    or all(image_choosable_by(item["value"], user) for item in items if isinstance(item, dict))
                )
            ):
                author.append({"type": "gallery", "value": [{"id": item["value"]} for item in items]})
            else:
                author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
        else:
            author.append(_unsupported_placeholder(block_type, path_prefix=path_prefix, index=index))
    return author


def overview_to_author_blocks(overview_value: list[dict]) -> list[dict]:
    """Backward-compatible wrapper for overview serialization."""
    return section_to_author_blocks(overview_value, path_prefix="overview")
