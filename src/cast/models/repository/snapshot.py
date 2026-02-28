from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image
from wagtail.models import Site

from .types import (
    AudioById,
    AudiosByPostID,
    CoverAltByPostID,
    CoverURLByPostID,
    HasAudioByID,
    ImageById,
    ImagesByPostID,
    PageUrlByID,
    PostByID,
    RenditionsForPost,
    TranscriptByAudioId,
    VideoById,
    VideosByPostID,
)

if TYPE_CHECKING:
    from cast.models import Post


def cache_page_url(post_id: int, url: str) -> None:
    """Store a page URL in the rich-text link cache to avoid DB lookups during rendering."""
    from ...wagtail_hooks import PageLinkHandlerWithCache

    PageLinkHandlerWithCache.cache_url(post_id, url)


class PostQuerySnapshot:
    """Container for pre-fetched data derived from a post queryset.

    Aggregates all media objects, renditions, page URLs, owner usernames,
    and cover images for a set of posts so that downstream renderers
    (templates, feeds, serializers) can look up data by post/media ID
    without issuing additional queries.

    Use ``create_from_post_queryset`` to build an instance from a live
    Django queryset with all necessary prefetches applied.
    """

    def __init__(
        self,
        *,
        post_queryset: Any,  # FIXME: Post queryset or list[Post], but does not work
        post_by_id: PostByID,
        audios: AudioById,  # used in blocks
        podcast_audio_by_episode_id: AudioById,  # used in podcast rss feed for podcast:transcript elements
        transcript_by_audio_id: TranscriptByAudioId,  # used in podcast rss feed for podcast:transcript elements
        images: ImageById,
        videos: VideoById,
        audios_by_post_id: AudiosByPostID,
        videos_by_post_id: VideosByPostID,
        images_by_post_id: ImagesByPostID,
        owner_username_by_id: dict[int, str],
        has_audio_by_id: HasAudioByID,
        renditions_for_posts: RenditionsForPost,
        page_url_by_id: PageUrlByID,
        absolute_page_url_by_id: PageUrlByID,
        cover_by_post_id: CoverURLByPostID,
        cover_alt_by_post_id: CoverAltByPostID,
    ):
        self.queryset = post_queryset
        self.post_by_id = post_by_id
        self.audios = audios
        self.images = images
        self.videos = videos
        self.audios_by_post_id = audios_by_post_id
        self.podcast_audio_by_episode_id = podcast_audio_by_episode_id
        self.transcript_by_audio_id = transcript_by_audio_id
        self.videos_by_post_id = videos_by_post_id
        self.images_by_post_id = images_by_post_id
        self.owner_username_by_id = owner_username_by_id
        self.has_audio_by_id = has_audio_by_id
        self.renditions_for_posts = renditions_for_posts
        self.page_url_by_id = page_url_by_id
        self.absolute_page_url_by_id = absolute_page_url_by_id
        self.cover_by_post_id = cover_by_post_id
        self.cover_alt_by_post_id = cover_alt_by_post_id

    @classmethod
    def create_from_post_queryset(
        cls, *, request: HttpRequest, site: Site, queryset: QuerySet["Post"], is_podcast: bool = False
    ) -> "PostQuerySnapshot":
        """Build a ``PostQuerySnapshot`` instance from a post queryset.

        Apply ``select_related`` and ``prefetch_related`` to minimize
        database round-trips, then iterate the queryset to populate the
        primary post and media lookup dicts. Renditions are collected
        separately via ``Post.get_all_renditions_from_queryset``.
        """
        if False:
            queryset = queryset.select_related("owner", "cover_image", "podcast_audio__transcript")
        else:
            queryset = queryset.select_related("owner", "cover_image")
        queryset = queryset.prefetch_related(
            "audios",
            "images",
            "videos",
            "galleries",
            "galleries__images",
            "images__renditions",
            "galleries__images__renditions",
        )
        post_by_id: PostByID = {}
        images, has_audio_by_id, owner_username_by_id, videos, audios = {}, {}, {}, {}, {}
        cover_by_post_id: CoverURLByPostID = {}
        cover_alt_by_post_id: CoverAltByPostID = {}
        audios_by_post_id: AudiosByPostID = {}
        podcast_audio_by_episode_id: AudioById = {}
        transcript_by_audio_id: TranscriptByAudioId = {}
        videos_by_post_id: VideosByPostID = {}
        images_by_post_id: ImagesByPostID = {}
        page_url_by_id: PageUrlByID = {}
        absolute_page_url_by_id: PageUrlByID = {}
        for post in queryset:
            specific_post = post.specific
            post_by_id[post.pk] = specific_post
            owner_username_by_id[post.pk] = post.owner.username
            has_audio_by_id[post.pk] = post.has_audio
            page_url_by_id[post.pk] = post.get_url(request=request, current_site=site)
            absolute_page_url_by_id[post.pk] = post.full_url
            cover_image_url = ""
            if post.cover_image is not None:
                cover_image_url = cast(Image, post.cover_image).file.url
            cover_by_post_id[post.pk] = cover_image_url
            cover_alt_by_post_id[post.pk] = post.cover_alt_text

            for image_type, image in post.get_all_images():
                images[image.pk] = image
                images_by_post_id.setdefault(post.pk, set()).add(image.pk)
            for video in post.videos.all():
                videos[video.pk] = video
                videos_by_post_id.setdefault(post.pk, set()).add(video.pk)
            for audio in post.audios.all():
                audios[audio.pk] = audio
                audios_by_post_id.setdefault(post.pk, set()).add(audio.pk)
            if hasattr(specific_post, "podcast_audio"):
                podcast_audio = specific_post.podcast_audio
                if podcast_audio is not None:
                    podcast_audio_by_episode_id[post.pk] = podcast_audio
                    try:
                        transcript_by_audio_id[podcast_audio.pk] = podcast_audio.transcript
                    except (ObjectDoesNotExist, AttributeError):
                        pass

        from ..pages import Post

        return cls(
            post_queryset=queryset,
            post_by_id=post_by_id,
            audios=audios,
            images=images,
            videos=videos,
            audios_by_post_id=audios_by_post_id,
            podcast_audio_by_episode_id=podcast_audio_by_episode_id,
            transcript_by_audio_id=transcript_by_audio_id,
            videos_by_post_id=videos_by_post_id,
            images_by_post_id=images_by_post_id,
            has_audio_by_id=has_audio_by_id,
            renditions_for_posts=Post.get_all_renditions_from_queryset(queryset),
            owner_username_by_id=owner_username_by_id,
            page_url_by_id=page_url_by_id,
            absolute_page_url_by_id=absolute_page_url_by_id,
            cover_by_post_id=cover_by_post_id,
            cover_alt_by_post_id=cover_alt_by_post_id,
        )


# Backward compatibility alias for the pre-Phase-2 public name.
QuerysetData = PostQuerySnapshot
