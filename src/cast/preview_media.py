"""Request-local media for previews, without synchronizing persisted relationships."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import router
from django.db.models import Prefetch
from wagtail.images.models import Filter, Image, Rendition

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

        using = post._state.db or router.db_for_read(type(post), instance=post)
        # Bind Wagtail's related rendition creation queryset to this database.
        # Preview reads and writes deliberately bypass its shared rendition cache.
        images = (
            Image.objects.using(using)
            .prefetch_related(Prefetch("renditions", queryset=Rendition.objects.using(using)))
            .in_bulk(ids["image"] | ids["gallery"])
        )
        kinds: tuple[tuple[str, ImageType], ...] = (("image", "regular"), ("gallery", "gallery"))
        images_with_type = [(image_type, images[pk]) for kind, image_type in kinds for pk in ids[kind] if pk in images]
        # Renditions are derived cache data. Never delete obsolete renditions here.
        _, missing = get_obsolete_and_missing_rendition_strings(images_with_type, using=using)
        for image_id, specs in missing.items():
            for spec in specs:
                # create_rendition uses get_or_create but does not publish to
                # Wagtail's shared cache, whose keys omit the database alias.
                image = images[image_id]
                image.create_rendition(image.clean_filter_for_svg(Filter(spec)))
        renditions: RenditionsForPosts = {}
        for rendition in Rendition.objects.using(using).filter(image_id__in=images):
            renditions.setdefault(rendition.image_id, []).append(rendition)
        return cls(
            images,
            Audio.objects.using(using).in_bulk(ids["audio"]),
            Video.objects.using(using).in_bulk(ids["video"]),
            renditions,
        )
