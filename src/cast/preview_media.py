"""Request-local media for previews, without synchronizing persisted relationships."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import connections, router
from django.db.models import Model, Prefetch
from wagtail.images import get_image_model
from wagtail.images.models import Filter

from .blocks import gallery_item_parts
from .models.image_renditions import get_all_filterstrings
from .models.repository.types import AudioById, ImageById, RenditionsForPosts, VideoById
from .renditions import ImageType

if TYPE_CHECKING:
    from .models import Post


def _media_id(value: Any, *, max_id: int = 2**63 - 1) -> int | None:
    if isinstance(value, dict):
        value = value.get("value")
    value = getattr(value, "pk", value)
    return value if type(value) is int and 0 < value <= max_id else None


def _max_media_id(using: str, model: type[Model]) -> int:
    """Return the largest admissible chooser ID, or 0 for non-integer primary keys."""
    try:
        return connections[using].ops.integer_field_range(model._meta.pk.get_internal_type())[1]
    except KeyError:
        # Backends without a range for this key type (e.g. UUID keys on PostgreSQL)
        # admit no integer chooser IDs, so previews skip such media instead of failing.
        return 0


@dataclass
class PreviewMedia:
    images: ImageById
    audios: AudioById
    videos: VideoById
    renditions: RenditionsForPosts

    @classmethod
    def from_post(cls, post: "Post") -> "PreviewMedia":
        from .models import Audio, Video

        image_model = get_image_model()
        rendition_model = image_model.get_rendition_model()
        using = post._state.db or router.db_for_read(type(post), instance=post)
        models_by_kind = {"image": image_model, "gallery": image_model, "audio": Audio, "video": Video}
        max_ids = {kind: _max_media_id(using, model) for kind, model in models_by_kind.items()}
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
                    if (pk := _media_id(value, max_id=max_ids[kind])) is not None:
                        ids[kind].add(pk)

        # Bind Wagtail's related rendition creation queryset to this database.
        # Preview reads and writes deliberately bypass its shared rendition cache.
        images = (
            image_model.objects.using(using)
            .prefetch_related(Prefetch("renditions", queryset=rendition_model.objects.using(using)))
            .in_bulk(ids["image"] | ids["gallery"])
        )
        kinds: tuple[tuple[str, ImageType], ...] = (("image", "regular"), ("gallery", "gallery"))
        images_with_type = [(image_type, images[pk]) for kind, image_type in kinds for pk in ids[kind] if pk in images]
        prefetched = [rendition for image in images.values() for rendition in image.renditions.all()]
        available = {(rendition.image_id, rendition.filter_spec) for rendition in prefetched}
        requested: dict[tuple[int, str], Filter] = {}
        for image_id, spec in get_all_filterstrings(images_with_type):
            image = images[image_id]
            # Wagtail 7.0 predates clean_filter_for_svg and uses the original filter.
            clean_filter = getattr(image, "clean_filter_for_svg", lambda value: value)
            image_filter = clean_filter(Filter(spec))
            requested[image_id, image_filter.spec] = image_filter
        missing = requested.keys() - available
        # Renditions are derived cache data. Never delete obsolete renditions here.
        for image_id, spec in missing:
            # create_rendition uses get_or_create but does not publish to
            # Wagtail's shared cache, whose keys omit the database alias.
            images[image_id].create_rendition(requested[image_id, spec])
        rows = rendition_model.objects.using(using).filter(image_id__in=images) if missing else prefetched
        renditions: RenditionsForPosts = {}
        for rendition in rows:
            renditions.setdefault(rendition.image_id, []).append(rendition)
        return cls(
            images,
            Audio.objects.using(using).in_bulk(ids["audio"]),
            Video.objects.using(using).in_bulk(ids["video"]),
            renditions,
        )
