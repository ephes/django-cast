import json
from typing import TYPE_CHECKING, Any, cast

from wagtail.images.models import Rendition

from .types import RenditionsForPosts, SerializedRenditions

if TYPE_CHECKING:
    from cast.models import Blog, Contributor, ContributorLink, EpisodeContributor


def serialize_audio(audio) -> dict:
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


def deserialize_audio(data: dict[str, Any]):
    """Reconstruct an Audio model instance from a serialized dict."""
    from .. import Audio

    return Audio(**data)


def serialize_transcript(transcript) -> dict:
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


def deserialize_transcript(data: dict[str, Any]):
    """Reconstruct a Transcript model instance from a serialized dict."""
    from .. import Transcript

    return Transcript(**data)


def serialize_contributor_link(link: "ContributorLink") -> dict[str, Any]:
    """Serialize a contributor link for feed/detail cache data."""
    return {
        "id": link.pk,
        "pk": link.pk,
        "service": link.service,
        "url": link.url,
        "sort_order": link.sort_order,
    }


def deserialize_contributor_link(data: dict[str, Any], contributor: "Contributor") -> "ContributorLink":
    """Reconstruct a contributor link and attach its contributor."""
    from ..contributors import ContributorLink

    link_data = data.copy()
    # Keep the reconstructed link attached to the reconstructed contributor so
    # EpisodeContributor.clean() sees matching contributor_id values.
    link_data["contributor"] = contributor
    return ContributorLink(**link_data)


def serialize_contributor(contributor: "Contributor") -> dict[str, Any]:
    """Serialize a contributor snippet for feed/detail cache data."""
    data = {
        "id": contributor.pk,
        "pk": contributor.pk,
        "display_name": contributor.display_name,
        "slug": contributor.slug,
        "visible": contributor.visible,
        "default_role": contributor.default_role,
        "short_bio": contributor.short_bio,
    }
    if contributor.avatar is not None:
        data["avatar"] = serialize_image(contributor.avatar)
    rendition_url = getattr(contributor, "_avatar_rendition_url", None)
    if rendition_url is not None:
        data["avatar_rendition_url"] = rendition_url
    return data


def deserialize_contributor(data: dict[str, Any]) -> "Contributor":
    """Reconstruct a contributor snippet."""
    from ..contributors import Contributor

    contributor_data = data.copy()
    avatar_data = contributor_data.pop("avatar", None)
    rendition_url = contributor_data.pop("avatar_rendition_url", None)
    contributor = Contributor(**contributor_data)
    if avatar_data is not None:
        contributor.avatar = deserialize_image(avatar_data)
    if rendition_url is not None:
        contributor._avatar_rendition_url = rendition_url
    return contributor


def serialize_episode_contributor(assignment: "EpisodeContributor") -> dict[str, Any]:
    """Serialize an episode contributor assignment."""
    data = {
        "id": assignment.pk,
        "pk": assignment.pk,
        "role": assignment.role,
        "sort_order": assignment.sort_order,
        "contributor": serialize_contributor(assignment.contributor),
    }
    if assignment.link is not None:
        data["link"] = serialize_contributor_link(assignment.link)
    return data


def deserialize_episode_contributor(data: dict[str, Any]) -> "EpisodeContributor":
    """Reconstruct an episode contributor assignment."""
    from ..contributors import EpisodeContributor

    assignment_data = data.copy()
    contributor = deserialize_contributor(assignment_data.pop("contributor"))
    link_data = assignment_data.pop("link", None)
    assignment_data["contributor"] = contributor
    if link_data is not None:
        assignment_data["link"] = deserialize_contributor_link(link_data, contributor)
    return EpisodeContributor(**assignment_data)


def serialize_video(video) -> dict:
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


def deserialize_video(data: dict[str, Any]):
    """Reconstruct a Video model instance from a serialized dict."""
    from .. import Video

    return Video(**data)


def serialize_blog(blog):
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


def deserialize_blog(data: dict[str, Any]) -> "Blog":
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


def serialize_post(post):
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


def deserialize_post(data: dict[str, Any]):
    """Reconstruct a Post instance from a serialized dict."""
    from .. import Post

    return Post(**data)


def serialize_episode(post):
    """Serialize an Episode instance (post with podcast audio) to a plain dict."""
    data = {
        "id": post.pk,
        "pk": post.pk,
        "uuid": post.uuid,
        "slug": post.slug,
        "title": post.title,
        "visible_date": post.visible_date,
        "comments_enabled": post.comments_enabled,
        "body": json.dumps(list(post.body.raw_data)),
        "podcast_audio": serialize_audio(post.podcast_audio),
        "keywords": post.keywords,
        "explicit": post.explicit,
        "block": post.block,
    }
    data["contributor_assignments"] = [
        serialize_episode_contributor(assignment) for assignment in post.visible_contributor_assignments
    ]
    return data


def deserialize_episode(data: dict[str, Any]):
    """Reconstruct an Episode instance from a serialized dict."""
    from .. import Episode

    episode_data = data.copy()
    if "podcast_audio" in episode_data:
        episode_data["podcast_audio"] = deserialize_audio(episode_data["podcast_audio"])
    assignments_data = episode_data.pop("contributor_assignments", [])
    episode = Episode(**episode_data)
    episode._visible_contributor_assignments = [
        deserialize_episode_contributor(assignment_data) for assignment_data in assignments_data
    ]
    return episode


def serialize_image(image):
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


def deserialize_image(data: dict[str, Any]):
    """Reconstruct an Image instance from a serialized dict."""
    from wagtail.images.models import Image

    return Image(**data)


def rendition_to_dict(rendition):
    """Serialize a Wagtail Rendition instance to a plain dict."""
    return {
        "pk": rendition.pk,
        "filter_spec": rendition.filter_spec,
        "file": rendition.file.name,
        "width": rendition.width,
        "height": rendition.height,
    }


def serialize_renditions(renditions_for_posts: RenditionsForPosts) -> SerializedRenditions:
    """Convert rendition model instances to dicts keyed by post PK."""
    renditions = {}
    for post_pk, renditions_for_post in renditions_for_posts.items():
        renditions[post_pk] = [rendition_to_dict(rendition) for rendition in renditions_for_post]
    return renditions


def deserialize_renditions(renditions: SerializedRenditions) -> RenditionsForPosts:
    """Reconstruct Rendition model instances from serialized dicts."""
    return {
        post_pk: [Rendition(**rendition) for rendition in renditions] for post_pk, renditions in renditions.items()
    }
