"""Permission-aware media reference resolution for content conversion."""

from __future__ import annotations

from typing import Any

from wagtail.images import get_image_model
from wagtail.images.permissions import permission_policy as image_permission_policy

from cast.media_permissions import audio_permission_policy, video_permission_policy
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
    return get_choosable_object(image_id, user, queryset=get_image_model().objects, policy=image_permission_policy)


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
