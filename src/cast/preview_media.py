"""Request-local media for previews, without synchronizing persisted relationships."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wagtail.images.models import Image, Rendition

from .blocks import gallery_item_parts
from .models.image_renditions import get_obsolete_and_missing_rendition_strings
from .models.repository.types import AudioById, ImageById, RenditionsForPosts, VideoById
from .renditions import ImageType

if TYPE_CHECKING:
    from .models import Post


def _media_id(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("value")
    value = getattr(value, "pk", value)
    return value if isinstance(value, int) else None


@dataclass
class PreviewMedia:
    images: ImageById
    audios: AudioById
    videos: VideoById
    renditions: RenditionsForPosts

    @classmethod
    def from_post(cls, post: "Post") -> "PreviewMedia":
        from .models import Audio, Video

        ids: dict[str, set[int]] = {kind: set() for kind in ("image", "gallery", "audio", "video")}
        for section in post.body:
            for block in section.value:
                kind = block.block_type
                if kind not in ids:
                    continue
                values = block.value.get("gallery", []) if kind == "gallery" else [block.value]
                for value in values:
                    if kind == "gallery":
                        value, _caption = gallery_item_parts(value)
                    if (pk := _media_id(value)) is not None:
                        ids[kind].add(pk)

        images = Image.objects.in_bulk(ids["image"] | ids["gallery"])
        kinds: tuple[tuple[str, ImageType], ...] = (("image", "regular"), ("gallery", "gallery"))
        images_with_type = [(image_type, images[pk]) for kind, image_type in kinds for pk in ids[kind] if pk in images]
        # Renditions are derived cache data. Never delete obsolete renditions here.
        _, missing = get_obsolete_and_missing_rendition_strings(images_with_type)
        for image_id, specs in missing.items():
            for spec in specs:
                # Wagtail persists new renditions itself and may normalize a
                # spec to an existing row. Do not save that cached row again.
                images[image_id].get_rendition(spec)
        renditions: RenditionsForPosts = {}
        for rendition in Rendition.objects.filter(image_id__in=images):
            renditions.setdefault(rendition.image_id, []).append(rendition)
        return cls(images, Audio.objects.in_bulk(ids["audio"]), Video.objects.in_bulk(ids["video"]), renditions)
