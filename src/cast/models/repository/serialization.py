import json
from typing import TYPE_CHECKING, Any, TypeVar, cast

from django.db import connections
from django.db.models import ForeignKey, Model
from wagtail.images.models import Image, Rendition

from .types import RenditionsForPosts, SerializedRenditions

if TYPE_CHECKING:
    from cast.models import (
        Audio,
        Blog,
        Contributor,
        ContributorLink,
        Episode,
        EpisodeContributor,
        Post,
        Season,
        Transcript,
        Video,
    )


_Model = TypeVar("_Model", bound=Model)


def _database_fields(instance: Model) -> dict[str, Any]:
    """Keep source identity in trusted, request-scoped projections only."""
    using = getattr(getattr(instance, "_state", None), "db", None)
    return {} if using is None else {"_database": using}


def _model_from_data(model: type[_Model], data: dict[str, Any]) -> _Model:
    """Restore a projection with Django's supported database hydration hook."""
    fields = data.copy()
    using = fields.pop("_database", None)
    if using is not None and using not in connections:
        raise ValueError("Unknown repository database.")
    # Keep projection defaults and explicitly supplied related objects, without
    # turning omitted fields into deferred database reads during rendering.
    instance = model(**fields)
    names = [field.attname for field in model._meta.concrete_fields]
    restored = model.from_db(using, names, [getattr(instance, name) for name in names])
    for field in model._meta.concrete_fields:
        if isinstance(field, ForeignKey) and field.is_cached(instance):
            field.set_cached_value(restored, field.get_cached_value(instance))
    return restored


def _collection_fields(collection_id: int | None) -> dict[str, Any]:
    """Serialize a nullable collection foreign key.

    A set key is kept as ``collection_id``; an unset one becomes ``collection=None``
    so the rebuilt instance does not look up a collection.
    """
    if collection_id is not None:
        return {"collection_id": collection_id}
    return {"collection": None}


def serialize_audio(audio: "Audio") -> dict[str, Any]:
    """Serialize an Audio model instance to a plain dict for caching."""
    data = {
        **_database_fields(audio),
        "id": audio.pk,
        "duration": audio.duration,
        # The revision guards the size cache write (see ``Audio._remember_file_size``).
        "modified": audio.modified,
        "title": audio.title,
        "subtitle": audio.subtitle,
        "data": audio.data,
        "m4a": audio.m4a.name,
        "mp3": audio.mp3.name,
        "oga": audio.oga.name,
        "opus": audio.opus.name,
    }
    data.update(_collection_fields(audio.collection_id))
    return data


def deserialize_audio(data: dict[str, Any]) -> "Audio":
    """Reconstruct an Audio model instance from a serialized dict."""
    from .. import Audio

    audio_data = data.copy()
    if "duration" in audio_data:
        audio_data["duration"] = Audio._meta.get_field("duration").to_python(audio_data["duration"])
    if "modified" in audio_data:
        audio_data["modified"] = Audio._meta.get_field("modified").to_python(audio_data["modified"])
    return _model_from_data(Audio, audio_data)


def serialize_transcript(transcript: "Transcript") -> dict[str, Any]:
    """Serialize a Transcript model instance to a plain dict for caching."""
    data = {
        **_database_fields(transcript),
        "id": transcript.pk,
        "audio_id": transcript.audio_id,
        "podlove": transcript.podlove.name,
        "vtt": transcript.vtt.name,
        "dote": transcript.dote.name,
    }
    data.update(_collection_fields(transcript.collection_id))
    return data


def deserialize_transcript(data: dict[str, Any]) -> "Transcript":
    """Reconstruct a Transcript model instance from a serialized dict."""
    from .. import Transcript

    return _model_from_data(Transcript, data)


def serialize_contributor_link(link: "ContributorLink") -> dict[str, Any]:
    """Serialize a contributor link for feed/detail cache data."""
    return {
        **_database_fields(link),
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
    return _model_from_data(ContributorLink, link_data)


def serialize_contributor(contributor: "Contributor") -> dict[str, Any]:
    """Serialize a contributor snippet for feed/detail cache data."""
    data = {
        **_database_fields(contributor),
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
    contributor = _model_from_data(Contributor, contributor_data)
    if avatar_data is not None:
        contributor.avatar = deserialize_image(avatar_data)
    if rendition_url is not None:
        contributor._avatar_rendition_url = rendition_url
    return contributor


def serialize_episode_contributor(assignment: "EpisodeContributor") -> dict[str, Any]:
    """Serialize an episode contributor assignment."""
    data = {
        **_database_fields(assignment),
        "id": assignment.pk,
        "pk": assignment.pk,
        "episode_id": assignment.episode_id,
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
    return _model_from_data(EpisodeContributor, assignment_data)


def serialize_season(season: "Season") -> dict[str, Any]:
    """Serialize a podcast season for feed cache data."""
    return {
        **_database_fields(season),
        "id": season.pk,
        "podcast_id": season.podcast_id,
        "number": season.number,
        "name": season.name,
    }


def deserialize_season(data: dict[str, Any]) -> "Season":
    """Reconstruct a podcast season from serialized feed cache data."""
    from .. import Season

    return _model_from_data(Season, data)


def serialize_video(video: "Video") -> dict[str, Any]:
    """Serialize a Video model instance to a plain dict for caching."""
    data = {
        **_database_fields(video),
        "id": video.pk,
        "title": video.title,
        "original": video.original.name,
        "poster": video.poster.name,
        "poster_seconds": video.poster_seconds,
    }
    data.update(_collection_fields(video.collection_id))
    return data


def deserialize_video(data: dict[str, Any]) -> "Video":
    """Reconstruct a Video model instance from a serialized dict."""
    from .. import Video

    return _model_from_data(Video, data)


def serialize_blog(blog: "Blog") -> dict[str, Any]:
    """Serialize a Blog (or Podcast) model instance to a plain dict for caching."""
    from .. import Podcast

    is_podcast = isinstance(blog, Podcast)
    data = {
        "type": "podcast" if is_podcast else "blog",
        **_database_fields(blog),
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
    from ..itunes import ItunesArtWork

    if is_podcast:
        data["itunes_categories"] = blog.itunes_categories
        data["keywords"] = blog.keywords
        data["explicit"] = blog.explicit
        data["itunes_type"] = blog.itunes_type
        if blog.itunes_artwork is not None:
            artwork = cast(ItunesArtWork, blog.itunes_artwork)
            data["itunes_artwork"] = {
                **_database_fields(artwork),
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
    # serialize_blog always writes the discriminator; the cachable data never outlives the request.
    blog_type = blog_data.pop("type")
    itunes_artwork_data = blog_data.pop("itunes_artwork", None)
    blog_class = Podcast if blog_type == "podcast" else Blog
    blog = _model_from_data(blog_class, blog_data)
    if itunes_artwork_data is not None:
        blog.itunes_artwork = _model_from_data(ItunesArtWork, itunes_artwork_data)
    return blog


def _serialize_post_common(post: "Post") -> dict[str, Any]:
    """Serialize the fields shared by every post type (plain posts and episodes).

    Both ``serialize_post`` and ``serialize_episode`` build on this helper so the
    shared field set cannot drift apart again (a missing ``last_published_at``
    used to drop the Atom ``<updated>`` element from podcast feeds).
    """
    return {
        **_database_fields(post),
        "id": post.pk,
        "pk": post.pk,
        "uuid": post.uuid,
        "slug": post.slug,
        "title": post.title,
        "visible_date": post.visible_date,
        "last_published_at": post.last_published_at,
        "comments_enabled": post.comments_enabled,
        "body": json.dumps(list(post.body.raw_data)),
    }


def serialize_post(post: "Post") -> dict[str, Any]:
    """Serialize a Post instance to a plain dict for caching."""
    return {"type": "post", **_serialize_post_common(post)}


def deserialize_post(data: dict[str, Any]) -> "Post":
    """Reconstruct a Post instance from a serialized dict."""
    from .. import Post

    post_data = data.copy()
    post_data.pop("type", None)
    for name in ("uuid", "visible_date", "last_published_at"):
        if name in post_data:
            post_data[name] = Post._meta.get_field(name).to_python(post_data[name])
    return _model_from_data(Post, post_data)


def serialize_episode(post: "Episode") -> dict[str, Any]:
    """Serialize an Episode instance (post with optional podcast audio) to a plain dict."""
    podcast_audio = post.podcast_audio
    data: dict[str, Any] = {
        "type": "episode",
        **_serialize_post_common(post),
        # podcast_audio is nullable (SET_NULL), so an episode can be live without audio.
        "podcast_audio": None if podcast_audio is None else serialize_audio(podcast_audio),
        "keywords": post.keywords,
        "explicit": post.explicit,
        "block": post.block,
        "episode_number": post.episode_number,
        "episode_type": post.episode_type,
    }
    if post.season is not None:
        data["season"] = serialize_season(post.season)
    data["contributor_assignments"] = [
        serialize_episode_contributor(assignment) for assignment in post.visible_contributor_assignments
    ]
    return data


def deserialize_episode(data: dict[str, Any]) -> "Episode":
    """Reconstruct an Episode instance from a serialized dict."""
    from .. import Episode

    episode_data = data.copy()
    episode_data.pop("type", None)
    if (podcast_audio_data := episode_data.get("podcast_audio")) is not None:
        episode_data["podcast_audio"] = deserialize_audio(podcast_audio_data)
    if (season_data := episode_data.get("season")) is not None:
        episode_data["season"] = deserialize_season(season_data)
    assignments_data = episode_data.pop("contributor_assignments", [])
    for name in ("uuid", "visible_date", "last_published_at"):
        if name in episode_data:
            episode_data[name] = Episode._meta.get_field(name).to_python(episode_data[name])
    episode = _model_from_data(Episode, episode_data)
    episode._visible_contributor_assignments = [
        deserialize_episode_contributor(assignment_data) for assignment_data in assignments_data
    ]
    return episode


def serialize_image(image: Image) -> dict[str, Any]:
    """Serialize a Wagtail Image instance to a plain dict for caching."""
    data = {
        **_database_fields(image),
        "pk": image.pk,
        "title": image.title,
        "file": image.file.name,
        "width": image.width,
        "height": image.height,
    }
    data.update(_collection_fields(image.collection_id))
    return data


def deserialize_image(data: dict[str, Any]) -> Image:
    """Reconstruct an Image instance from a serialized dict."""
    from wagtail.images.models import Image

    return _model_from_data(Image, data)


def rendition_to_dict(rendition: Rendition) -> dict[str, Any]:
    """Serialize a Wagtail Rendition instance to a plain dict."""
    return {
        **_database_fields(rendition),
        "pk": rendition.pk,
        "image_id": rendition.image_id,
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
        post_pk: [_model_from_data(Rendition, rendition) for rendition in renditions]
        for post_pk, renditions in renditions.items()
    }
