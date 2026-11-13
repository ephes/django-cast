"""Permission-aware media reference resolution for content conversion."""

from __future__ import annotations

from typing import Any

from wagtail.images import get_image_model

from cast.media_permissions import audio_permission_policy, get_image_permission_policy, video_permission_policy
from cast.models import Audio, Video


def get_choosable_object(obj_id: Any, user: Any, *, queryset: Any, policy: Any) -> Any | None:
    """Return an object when ``user`` may choose it, otherwise ``None``."""
    if user is None:
        raise TypeError("user is required to resolve media refs")
    if not isinstance(obj_id, int) or isinstance(obj_id, bool):
        return None
    visible = policy.instances_user_has_permission_for(user, "choose")
    return queryset.filter(pk=obj_id, pk__in=visible.values("pk")).first()


def get_choosable_image(image_id: Any, user: Any) -> Any | None:
    """Return the image when it exists and the caller may choose it."""
    return get_choosable_object(
        image_id, user, queryset=get_image_model().objects, policy=get_image_permission_policy()
    )


def image_choosable_by(image_id: Any, user: Any) -> bool:
    """Return whether the image exists and the caller may choose it."""
    return get_choosable_image(image_id, user) is not None


def get_choosable_audio(audio_id: Any, user: Any) -> Any | None:
    """Return the audio when it exists and the caller may choose it."""
    return get_choosable_object(audio_id, user, queryset=Audio.objects, policy=audio_permission_policy)


def audio_choosable_by(audio_id: Any, user: Any) -> bool:
    """Return whether the audio exists and the caller may choose it."""
    return get_choosable_audio(audio_id, user) is not None


def get_choosable_video(video_id: Any, user: Any) -> Any | None:
    """Return the video when it exists and the caller may choose it."""
    return get_choosable_object(video_id, user, queryset=Video.objects, policy=video_permission_policy)


def video_choosable_by(video_id: Any, user: Any) -> bool:
    """Return whether the video exists and the caller may choose it."""
    return get_choosable_video(video_id, user) is not None


def _media_ref_is_available(block_type: str, value: Any, user: Any) -> bool:
    """Compatibility helper retained for private tests until converter slice 7."""
    if block_type == "image":
        return image_choosable_by(value, user)
    if block_type == "audio":
        return audio_choosable_by(value, user)
    if block_type == "video":
        return video_choosable_by(value, user)
    raise ValueError(f"Unsupported media block type: {block_type}")


class MediaResolution:
    """Permission results owned by one conversion, one user and routed querysets."""

    batch_size = 500

    def __init__(self, user: Any) -> None:
        self.user = user
        self._objects: dict[tuple[str, str], dict[int, Any]] = {}

    def prefetch(self, blocks: list[Any], *, stored: bool) -> None:
        from cast.blocks import gallery_item_parts

        ids: dict[str, set[int]] = {"image": set(), "audio": set(), "video": set()}
        for block in blocks:
            if not isinstance(block, dict):
                continue
            kind, value = block.get("type"), block.get("value")
            refs = []
            if isinstance(kind, str) and kind in ids:
                refs = [value if stored else value.get("id") if isinstance(value, dict) else None]
            elif kind == "gallery":
                items = value.get("gallery", []) if stored and isinstance(value, dict) else value
                if isinstance(items, list):
                    refs = [
                        gallery_item_parts(item)[0] if stored else item.get("id") if isinstance(item, dict) else None
                        for item in items
                    ]
                kind = "image"
            else:
                continue
            ids[kind].update(ref for ref in refs if isinstance(ref, int) and not isinstance(ref, bool))
        for kind, object_ids in ids.items():
            if object_ids:
                self._prefetch_ids(kind, object_ids)

    def _prefetch_ids(self, kind: str, object_ids: set[int]) -> dict[int, Any]:
        if self.user is None:
            raise TypeError("user is required to resolve media refs")
        if kind == "image":
            queryset, policy = get_image_model().objects.all(), get_image_permission_policy()
        elif kind == "audio":
            queryset, policy = Audio.objects.all(), audio_permission_policy
        else:
            queryset, policy = Video.objects.all(), video_permission_policy
        # Pin both sides of the permission subquery to the model's routed DB.
        alias = queryset.db
        cached = self._objects.setdefault((kind, alias), {})
        missing = sorted(object_ids - cached.keys())
        if not missing:
            return cached
        visible = policy.instances_user_has_permission_for(self.user, "choose").using(alias)
        for offset in range(0, len(missing), self.batch_size):
            batch = missing[offset : offset + self.batch_size]
            cached.update(dict.fromkeys(batch))
            cached.update(
                {obj.pk: obj for obj in queryset.using(alias).filter(pk__in=batch).filter(pk__in=visible.values("pk"))}
            )

        return cached

    def resolve(self, kind: str, object_id: Any) -> Any | None:
        if self.user is None:
            raise TypeError("user is required to resolve media refs")
        if not isinstance(object_id, int) or isinstance(object_id, bool):
            return None
        return self._prefetch_ids(kind, {object_id}).get(object_id)
