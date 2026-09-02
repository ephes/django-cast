from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wagtail.fields import StreamField

    from cast.models.pages import Post

TypeToIdSet = dict[str, set[int]]


def sync_media_ids(from_database: TypeToIdSet, from_body: TypeToIdSet) -> tuple[TypeToIdSet, TypeToIdSet]:
    """Return media relationship ids to add and remove."""
    to_add: TypeToIdSet = {}
    to_remove: TypeToIdSet = {}
    all_media_types = set(from_database).union(from_body)
    for media_type in all_media_types:
        in_database_ids = from_database.get(media_type, set())
        in_body_ids = from_body.get(media_type, set())
        ids_to_add = in_body_ids - in_database_ids
        if ids_to_add:
            to_add[media_type] = ids_to_add
        ids_to_remove = in_database_ids - in_body_ids
        if ids_to_remove:
            to_remove[media_type] = ids_to_remove
    return to_add, to_remove


def media_ids_from_body(post: Post, body: StreamField) -> TypeToIdSet:
    """Extract built-in media ids from a Post StreamField value."""
    from wagtail.images.models import Image

    from cast.models.gallery import get_or_create_gallery

    from_body: TypeToIdSet = {}
    for content_block in body:
        for block in content_block.value:
            if block.block_type == "gallery":
                images = block.value.get("gallery", [])
                image_ids = []
                for image in images:
                    if isinstance(image, dict) and "value" in image:
                        image_ids.append(image["value"])
                    elif isinstance(image, Image):
                        image_ids.append(image.pk)
                    elif isinstance(image, int):
                        image_ids.append(image)
                media_model = get_or_create_gallery(image_ids)
            else:
                media_model = block.value
            if block.block_type not in post.media_model_lookup or media_model is None:
                continue
            if hasattr(media_model, "id"):
                from_body.setdefault(block.block_type, set()).add(media_model.id)
            elif isinstance(media_model, int):
                media_model_class = post.media_model_lookup[block.block_type]
                if media_model_class._default_manager.filter(pk=media_model).exists():
                    from_body.setdefault(block.block_type, set()).add(media_model)
            else:
                raise ValueError(f"media model {media_model} is not an instance of int or a model")
    return from_body


def synchronize_post_media(post: Post) -> None:
    """Synchronize built-in StreamField media into the Post relationships."""
    to_add, to_remove = sync_media_ids(post.media_ids_from_db, media_ids_from_body(post, post.body))
    media_attr_lookup = post.media_attr_lookup
    for media_type, ids in to_add.items():
        media_attr_lookup[media_type].add(*ids)
    for media_type, ids in to_remove.items():
        media_attr_lookup[media_type].remove(*ids)


def prepare_post_media(
    post: Post,
    *,
    sync_media: bool = True,
    create_renditions: bool = True,
) -> None:
    """Run the explicit synchronous media preparation required for a Post."""
    if sync_media:
        synchronize_post_media(post)
    if create_renditions:
        from cast.models.image_renditions import create_missing_renditions_for_posts

        create_missing_renditions_for_posts(iter([post]))


def prepare_published_post_media(sender: Any, instance: Any, **kwargs: Any) -> None:
    """Prepare Post media after any Wagtail publication path."""
    from cast.models.pages import Post

    if isinstance(instance, Post) and instance.live:
        prepare_post_media(instance)


def install_post_media_publish_handler() -> None:
    """Install the Wagtail publication boundary for Post media preparation."""
    from wagtail.signals import page_published

    page_published.connect(prepare_published_post_media, dispatch_uid="cast.prepare_published_post_media")
