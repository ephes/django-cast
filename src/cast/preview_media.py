"""Request-local media for previews, without synchronizing persisted relationships."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import connections, router
from django.db.models import Model, Prefetch
from wagtail.images import get_image_model
from wagtail.images.exceptions import InvalidFilterSpecError
from wagtail.images.models import Filter, SourceImageIOError

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
        requested: dict[int, dict[str, Filter]] = {}
        for image_id, spec in get_all_filterstrings(images_with_type):
            image = images[image_id]
            # Wagtail 7.0 predates clean_filter_for_svg and uses the original filter.
            clean_filter = getattr(image, "clean_filter_for_svg", lambda value: value)
            image_filter = clean_filter(Filter(spec))
            requested.setdefault(image_id, {})[image_filter.spec] = image_filter

        renditions: RenditionsForPosts = {}
        for image_id, image in images.items():
            missing = requested.get(image_id, {})
            for rendition in image.renditions.all():
                spec = rendition.filter_spec
                image_filter = missing.get(spec) or Filter(spec)
                try:
                    focal_key = image_filter.get_cache_key(image)
                except InvalidFilterSpecError:
                    # A cached fallback may use an operation that is no longer registered.
                    continue
                if rendition.focal_point_key == focal_key:
                    renditions.setdefault(image_id, []).append(rendition)
                    missing.pop(spec, None)
            # Keep obsolete cache rows. create_rendition uses get_or_create
            # without publishing to Wagtail's shared, alias-blind cache.
            for image_filter in missing.values():
                try:
                    rendition = image.create_rendition(image_filter)
                except SourceImageIOError:
                    # Keep cached variants and move on to the next image.
                    break
                renditions.setdefault(image_id, []).append(rendition)
        return cls(
            images,
            Audio.objects.using(using).in_bulk(ids["audio"]),
            Video.objects.using(using).in_bulk(ids["video"]),
            renditions,
        )
