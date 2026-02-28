import json
from typing import TYPE_CHECKING, Any, cast

from wagtail.images.models import Rendition

from .types import RenditionsForPost, SerializedRenditions

if TYPE_CHECKING:
    from cast.models import Blog


def audio_to_dict(audio) -> dict:
    """Serialize an Audio model instance to a plain dict for caching."""
    data = {
        "id": audio.pk,
        "duration": audio.duration,
        "title": audio.title,
        "subtitle": audio.subtitle,
        "data": audio.data,
        "m4a": audio.m4a.name,
        "mp3": audio.mp3.name,
        "oga": audio.oga.name,
        "opus": audio.opus.name,
    }
    if audio.collection_id is not None:
        data["collection_id"] = audio.collection_id
    else:
        data["collection"] = None
    return data


def transcript_to_dict(transcript) -> dict:
    """Serialize a Transcript model instance to a plain dict for caching."""
    data = {
        "id": transcript.pk,
        "audio_id": transcript.audio_id,
        "podlove": transcript.podlove.name,
        "vtt": transcript.vtt.name,
        "dote": transcript.dote.name,
    }
    if transcript.collection_id is not None:
        data["collection_id"] = transcript.collection_id
    else:
        data["collection"] = None
    return data


def video_to_dict(video) -> dict:
    """Serialize a Video model instance to a plain dict for caching."""
    data = {
        "id": video.pk,
        "title": video.title,
        "original": video.original.name,
        "poster": video.poster.name,
        "poster_seconds": video.poster_seconds,
    }
    if video.collection_id is not None:
        data["collection_id"] = video.collection_id
    else:
        data["collection"] = None
    return data


def blog_to_dict(blog):
    """Serialize a Blog (or Podcast) model instance to a plain dict for caching."""
    data = {
        "id": blog.pk,
        "pk": blog.pk,
        "title": blog.title,
        "subtitle": blog.subtitle,
        "author": blog.author,
        "slug": blog.slug,
        "uuid": blog.uuid,
        "email": blog.email,
        "comments_enabled": blog.comments_enabled,
        "noindex": blog.noindex,
        "template_base_dir": blog.template_base_dir,
        "description": blog.description,
    }
    from .. import Podcast
    from ..itunes import ItunesArtWork

    if isinstance(blog, Podcast):
        data["itunes_categories"] = blog.itunes_categories
        data["keywords"] = blog.keywords
        data["explicit"] = blog.explicit
        if blog.itunes_artwork is not None:
            artwork = cast(ItunesArtWork, blog.itunes_artwork)
            data["itunes_artwork"] = {
                "id": artwork.pk,
                "original": artwork.original.name,
                "original_height": artwork.original_height,
                "original_width": artwork.original_width,
            }
    return data


def blog_from_data(data: dict[str, Any]) -> "Blog":
    """Reconstruct a Blog or Podcast instance from a serialized dict."""
    from .. import Blog, Podcast
    from ..itunes import ItunesArtWork

    blog_data = data.copy()
    itunes_artwork_data = blog_data.pop("itunes_artwork", None)
    is_podcast = (
        any(field in blog_data for field in ("itunes_categories", "keywords", "explicit"))
        or itunes_artwork_data is not None
    )
    blog_class = Podcast if is_podcast else Blog
    blog = blog_class(**blog_data)
    if itunes_artwork_data is not None:
        blog.itunes_artwork = ItunesArtWork(**itunes_artwork_data)
    return blog


def post_to_dict(post):
    """Serialize a Post instance to a plain dict for caching."""
    return {
        "id": post.pk,
        "pk": post.pk,
        "uuid": post.uuid,
        "slug": post.slug,
        "title": post.title,
        "visible_date": post.visible_date,
        "comments_enabled": post.comments_enabled,
        "body": json.dumps(list(post.body.raw_data)),
    }


def episode_to_dict(post):
    """Serialize an Episode instance (post with podcast audio) to a plain dict."""
    return {
        "id": post.pk,
        "pk": post.pk,
        "uuid": post.uuid,
        "slug": post.slug,
        "title": post.title,
        "visible_date": post.visible_date,
        "comments_enabled": post.comments_enabled,
        "body": json.dumps(list(post.body.raw_data)),
        "podcast_audio": audio_to_dict(post.podcast_audio),
        "keywords": post.keywords,
        "explicit": post.explicit,
        "block": post.block,
    }


def image_to_dict(image):
    """Serialize a Wagtail Image instance to a plain dict for caching."""
    data = {
        "pk": image.pk,
        "title": image.title,
        "file": image.file.name,
        "width": image.width,
        "height": image.height,
    }
    if image.collection_id is not None:
        data["collection_id"] = image.collection_id
    else:
        data["collection"] = None
    return data


def rendition_to_dict(rendition):
    """Serialize a Wagtail Rendition instance to a plain dict."""
    return {
        "pk": rendition.pk,
        "filter_spec": rendition.filter_spec,
        "file": rendition.file.name,
        "width": rendition.width,
        "height": rendition.height,
    }


def serialize_renditions(renditions_for_posts: RenditionsForPost) -> SerializedRenditions:
    """Convert rendition model instances to dicts keyed by post PK."""
    renditions = {}
    for post_pk, renditions_for_post in renditions_for_posts.items():
        renditions[post_pk] = [rendition_to_dict(rendition) for rendition in renditions_for_post]
    return renditions


def deserialize_renditions(renditions: SerializedRenditions) -> RenditionsForPost:
    """Reconstruct Rendition model instances from serialized dicts."""
    return {
        post_pk: [Rendition(**rendition) for rendition in renditions] for post_pk, renditions in renditions.items()
    }
