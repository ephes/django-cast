from typing import TYPE_CHECKING, Any, cast

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image
from wagtail.models import Site

from .types import (
    AudioById,
    AudiosByPostID,
    ChaptersByAudioId,
    CoverAltByPostID,
    CoverURLByPostID,
    HasAudioByID,
    ImageById,
    ImagesByPostID,
    PageUrlByID,
    PostByID,
    RenditionsForPosts,
    TranscriptByAudioId,
    VideoById,
    VideosByPostID,
)

if TYPE_CHECKING:
    from cast.models import Audio, Post


def _serialize_chaptermarks(audio: "Audio") -> list[dict[str, str]]:
    """Serialize prefetched chapter marks without issuing ordering queries."""
    return [
        {"start": chaptermark.start.isoformat(), "title": chaptermark.title}
        for chaptermark in sorted(audio.chaptermarks.all(), key=lambda mark: mark.start)
    ]


def cache_page_url(post_id: int, url: str) -> None:
    """Store a page URL in the rich-text link cache to avoid DB lookups during rendering."""
    from ...wagtail_hooks import PageLinkHandlerWithCache

    PageLinkHandlerWithCache.cache_url(post_id, url)


def clear_cached_page_urls() -> None:
    """Clear rich-text link cache before building request-scoped repositories."""
    from ...wagtail_hooks import PageLinkHandlerWithCache

    PageLinkHandlerWithCache.cache.clear()


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
        chapters_by_audio_id: ChaptersByAudioId,  # used in podcast feeds for chapter elements
        images: ImageById,
        videos: VideoById,
        audios_by_post_id: AudiosByPostID,
        videos_by_post_id: VideosByPostID,
        images_by_post_id: ImagesByPostID,
        owner_username_by_id: dict[int, str],
        has_audio_by_id: HasAudioByID,
        renditions_for_posts: RenditionsForPosts,
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
        self.chapters_by_audio_id = chapters_by_audio_id
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
        cls, *, request: HttpRequest, site: Site | None, queryset: QuerySet["Post"]
    ) -> "PostQuerySnapshot":
        """Build a ``PostQuerySnapshot`` instance from a post queryset.

        Apply ``select_related`` and ``prefetch_related`` to minimize
        database round-trips, then iterate the queryset to populate the
        primary post and media lookup dicts. Renditions are collected
        separately via ``Post.get_all_renditions_from_queryset``.
        """
        from ..pages import Episode, Post

        queryset = queryset.select_related("owner", "cover_image", "content_type")
        queryset_model = getattr(queryset, "model", None)
        if isinstance(queryset_model, type) and issubclass(queryset_model, Episode):
            queryset = queryset.select_related("podcast_audio__transcript", "season").prefetch_related(
                "podcast_audio__chaptermarks"
            )
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
        chapters_by_audio_id: ChaptersByAudioId = {}
        videos_by_post_id: VideosByPostID = {}
        images_by_post_id: ImagesByPostID = {}
        page_url_by_id: PageUrlByID = {}
        absolute_page_url_by_id: PageUrlByID = {}
        episode_by_id: dict[int, Episode] = {}
        posts = list(queryset)
        specific_post_by_id: PostByID = {}
        pks_by_specific_model: dict[type[Post], list[int]] = {}
        for post in posts:
            specific_model_attr = getattr(post, "specific_class", None)
            if not isinstance(specific_model_attr, type) or not issubclass(specific_model_attr, Post):
                specific_post_by_id[post.pk] = post.specific
                continue
            specific_model = cast(type[Post], specific_model_attr)
            if isinstance(post, specific_model):
                specific_post_by_id[post.pk] = post
            else:
                pks_by_specific_model.setdefault(specific_model, []).append(post.pk)
        for specific_model, pks in pks_by_specific_model.items():
            specific_queryset = specific_model._default_manager.filter(pk__in=pks)
            if issubclass(specific_model, Episode):
                specific_queryset = specific_queryset.select_related(
                    "podcast_audio__transcript", "season"
                ).prefetch_related("podcast_audio__chaptermarks")
            specific_post_by_id.update(specific_queryset.in_bulk(pks))

        for post in posts:
            specific_post = specific_post_by_id[post.pk]
            post_by_id[post.pk] = specific_post
            owner_username_by_id[post.pk] = post.owner.username
            audios_count = 0
            try:
                audios_count = post.audios.count()
            except (AttributeError, ValueError):
                pass
            if getattr(post, "audio_in_body", False) or audios_count > 0:
                has_audio_by_id[post.pk] = True
            elif isinstance(specific_post, Episode):
                has_audio_by_id[post.pk] = specific_post.podcast_audio_id is not None
            else:
                has_audio_by_id[post.pk] = False
            page_url_by_id[post.pk] = post.get_url(request=request, current_site=site)
            absolute_page_url_by_id[post.pk] = post.full_url
            cover_image_url = ""
            if post.cover_image is not None:
                cover_image_url = cast(Image, post.cover_image).file.url
            cover_by_post_id[post.pk] = cover_image_url
            cover_alt_by_post_id[post.pk] = post.cover_alt_text

            for _, image in post.get_all_images():
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
                    marks = _serialize_chaptermarks(podcast_audio)
                    if marks:
                        chapters_by_audio_id[podcast_audio.pk] = marks
                    try:
                        transcript_by_audio_id[podcast_audio.pk] = podcast_audio.transcript
                    except ObjectDoesNotExist:
                        pass
            if isinstance(specific_post, Episode):
                episode_by_id[post.pk] = specific_post

        if episode_by_id:
            from ..contributors import EpisodeContributor

            assignments_by_episode_id: dict[int, list[EpisodeContributor]] = {
                episode_id: [] for episode_id in episode_by_id
            }
            primed_contributors: dict[int, Any] = {}
            for assignment in (
                EpisodeContributor.objects.filter(episode_id__in=episode_by_id, contributor__visible=True)
                .select_related("contributor__avatar", "link")
                .order_by("episode_id", "sort_order", "pk")
            ):
                if assignment.contributor_id in primed_contributors:
                    assignment.contributor = primed_contributors[assignment.contributor_id]
                else:
                    assignment.get_avatar_rendition_url()
                    primed_contributors[assignment.contributor_id] = assignment.contributor
                assignments_by_episode_id[assignment.episode_id].append(assignment)
            for episode_id, episode in episode_by_id.items():
                episode._visible_contributor_assignments = assignments_by_episode_id[episode_id]

        return cls(
            post_queryset=queryset,
            post_by_id=post_by_id,
            audios=audios,
            images=images,
            videos=videos,
            audios_by_post_id=audios_by_post_id,
            podcast_audio_by_episode_id=podcast_audio_by_episode_id,
            transcript_by_audio_id=transcript_by_audio_id,
            chapters_by_audio_id=chapters_by_audio_id,
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
