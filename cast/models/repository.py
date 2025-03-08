import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Optional, Protocol, TypeAlias, cast

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image, Rendition
from wagtail.models import Site

from ..filters import PostFilterset
from ..views import HtmxHttpRequest

if TYPE_CHECKING:
    from cast.blocks import (
        AudioChooserBlock,
        GalleryBlockWithLayout,
        ImageChooserBlock,
        VideoChooserBlock,
    )
    from cast.models import Audio, Blog, Episode, Post, Transcript, Video

PostByID: TypeAlias = dict[int, "Post"]
PageUrlByID: TypeAlias = dict[int, str]
HasAudioByID: TypeAlias = dict[int, bool]
AudiosByPostID: TypeAlias = dict[int, set["Audio"]]
AudioById: TypeAlias = dict[int, "Audio"]
TranscriptByAudioId: TypeAlias = dict[int, "Transcript"]
VideosByPostID: TypeAlias = dict[int, set["Video"]]
VideoById: TypeAlias = dict[int, "Video"]
ImagesByPostID: TypeAlias = dict[int, set["Image"]]
CoverURLByPostID: TypeAlias = dict[int, str]
CoverAltByPostID: TypeAlias = dict[int, str]
ImageById: TypeAlias = dict[int, Image]
RenditionsForPosts: TypeAlias = dict[int, list[Rendition]]
LinkTuples: TypeAlias = list[tuple[str, str]]
RenditionsForPost: TypeAlias = dict[int, list[Rendition]]
SerializedRenditions: TypeAlias = dict[int, list[dict]]
if TYPE_CHECKING:
    CastBlock: TypeAlias = (
        type["AudioChooserBlock"]
        | type["VideoChooserBlock"]
        | type["ImageChooserBlock"]
        | type["GalleryBlockWithLayout"]
    )


def cache_page_url(post_id: int, url: str) -> None:
    from ..wagtail_hooks import PageLinkHandlerWithCache

    PageLinkHandlerWithCache.cache_url(post_id, url)


class QuerysetData:
    """
    This class is a container for the data that is needed to render a list of posts
    and that only depends on the queryset of those posts.
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
    ) -> "QuerysetData":
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
            post_by_id[post.pk] = post.specific
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
            if hasattr(post, "podcast_audio"):
                podcast_audio_by_episode_id[post.pk] = post.podcast_audio

        from .pages import Post

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


class PostDetailRepository:
    """
    This class is a container for the data that is needed to render a post detail page.
    """

    def __init__(
        self,
        *,
        post_id: int,
        template_base_dir: str,
        blog: "Blog",
        root_nav_links: LinkTuples,
        comments_are_enabled: bool,
        has_audio: bool,
        page_url: str,
        absolute_page_url: str,
        owner_username: str,
        blog_url: str,
        cover_image_url: str,
        cover_alt_text: str,
        audio_by_id: AudioById,
        video_by_id: VideoById,
        image_by_id: ImageById,
        renditions_for_posts: RenditionsForPost,
    ):
        self.post_id = post_id
        self.template_base_dir = template_base_dir
        self.blog = blog
        self.root_nav_links = root_nav_links
        self.comments_are_enabled = comments_are_enabled
        self.has_audio = has_audio
        self.page_url = page_url
        self.absolute_page_url = absolute_page_url
        self.owner_username = owner_username
        self.blog_url = blog_url
        self.cover_image_url = cover_image_url
        self.cover_alt_text = cover_alt_text
        self.audio_by_id = audio_by_id
        self.video_by_id = video_by_id
        self.image_by_id = image_by_id
        self.renditions_for_posts = renditions_for_posts

        cache_page_url(post_id, page_url)

    @classmethod
    def create_from_django_models(cls, request: HttpRequest, post: "Post") -> "PostDetailRepository":
        blog = post.blog
        owner_username = "unknown"
        if post.owner is not None:
            owner_username = post.owner.username
        image_by_id = {}  # post.media_lookup.get("image", {}) is not enough because gallery images are missing
        for _, image in post.get_all_images():
            image_by_id[image.pk] = image
        cover_image_url = ""
        if post.cover_image is not None:
            cover_image_url = cast(Image, post.cover_image).file.url
        return cls(
            post_id=post.pk,
            template_base_dir=post.get_template_base_dir(request),
            blog=blog,
            comments_are_enabled=post.get_comments_are_enabled(blog),
            root_nav_links=[(p.get_url(), p.title) for p in blog.get_root().get_children().live()],
            has_audio=post.has_audio,
            page_url=post.get_url(request=request),
            absolute_page_url=post.get_full_url(request=request),
            owner_username=owner_username,
            blog_url=blog.get_url(request=request),
            cover_image_url=cover_image_url,
            cover_alt_text=post.cover_alt_text,
            audio_by_id=post.media_lookup.get("audio", {}),
            video_by_id=post.media_lookup.get("video", {}),
            image_by_id=image_by_id,
            renditions_for_posts=post.get_all_renditions_from_queryset([post]),
        )


class EpisodeFeedRepository:
    """
    This class is a container for the data that is needed to render an episode in the feed.
    """

    def __init__(
        self,
        *,
        podcast_audio: "Audio",
        transcript: Optional["Transcript"],
    ) -> None:
        self.podcast_audio = podcast_audio
        self.transcript = transcript


def audio_to_dict(audio) -> dict:
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
    return {
        "id": blog.pk,
        "pk": blog.pk,
        "author": blog.author,
        "slug": blog.slug,
        "uuid": blog.uuid,
        "email": blog.email,
        "comments_enabled": blog.comments_enabled,
        "noindex": blog.noindex,
        "template_base_dir": blog.template_base_dir,
        "description": blog.description,
    }


def post_to_dict(post):
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
    return {
        "pk": rendition.pk,
        "filter_spec": rendition.filter_spec,
        "file": rendition.file.name,
        "width": rendition.width,
        "height": rendition.height,
    }


def serialize_renditions(renditions_for_posts: RenditionsForPost) -> SerializedRenditions:
    renditions = {}
    for post_pk, renditions_for_post in renditions_for_posts.items():
        renditions[post_pk] = [rendition_to_dict(rendition) for rendition in renditions_for_post]
    return renditions


def deserialize_renditions(renditions: SerializedRenditions) -> RenditionsForPost:
    return {
        post_pk: [Rendition(**rendition) for rendition in renditions] for post_pk, renditions in renditions.items()
    }


Choice: TypeAlias = tuple[str, str]


class HasChoices(Protocol):
    choices: Iterable[Choice]


def get_facet_choices(fields: dict[str, HasChoices], field_name) -> list[Choice]:
    if field_name in fields:
        return [(k, v) for k, v in fields[field_name].choices if k != ""]
    return []


def add_site_raw(data: dict[str, Any]) -> dict:
    site_statement = """
        select
            id,
            hostname,
            port,
            site_name,
            root_page_id,
            is_default_site
        from
            wagtailcore_site
    """
    with connection.cursor() as cursor:
        cursor.execute(site_statement)
        columns = [col[0] for col in cursor.description]
        row_tuple = cursor.fetchone()
        data["site"] = dict(zip(columns, row_tuple))
    return data


def add_root_nav_links(data: dict[str, Any]) -> dict:
    site = Site(**data["site"])
    root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
    data["root_nav_links"] = root_nav_links
    return data


def add_queryset_data(data: dict[str, Any], queryset_data: QuerysetData) -> dict:
    # posts
    from .pages import Episode

    post_by_id = {}
    for pk, post in queryset_data.post_by_id.items():
        if isinstance(post, Episode):
            post_by_id[pk] = episode_to_dict(post)
        else:
            post_by_id[pk] = post_to_dict(post)
    data["post_by_id"] = post_by_id

    # audios
    audios = {}
    for pk, audio in queryset_data.audios.items():
        audios[pk] = audio_to_dict(audio)
    data["audios"] = audios

    # transcripts
    transcripts = {}
    for episode_id, audio in queryset_data.podcast_audio_by_episode_id.items():
        if hasattr(audio, "transcript"):
            transcripts[audio.pk] = transcript_to_dict(audio.transcript)

    # videos
    videos = {}
    for pk, video in queryset_data.videos.items():
        videos[pk] = video_to_dict(video)
    data["videos"] = videos

    # images
    images = {}
    for pk, image in queryset_data.images.items():
        images[pk] = image_to_dict(image)
    data["images"] = images

    # renditions
    data["renditions_for_posts"] = serialize_renditions(queryset_data.renditions_for_posts)
    data["posts"] = [post.pk for post in queryset_data.queryset]

    data["images_by_post_id"] = queryset_data.images_by_post_id
    data["videos_by_post_id"] = queryset_data.videos_by_post_id
    data["audios_by_post_id"] = queryset_data.audios_by_post_id
    data["podcast_audio_by_episode_id"] = {
        episode_id: audio_to_dict(audio) for episode_id, audio in queryset_data.podcast_audio_by_episode_id.items()
    }
    data["transcripts"] = transcripts
    data["cover_by_post_id"] = queryset_data.cover_by_post_id
    data["cover_alt_by_post_id"] = queryset_data.cover_alt_by_post_id
    data["has_audio_by_id"] = queryset_data.has_audio_by_id
    data["owner_username_by_id"] = queryset_data.owner_username_by_id
    return data


def data_for_blog_cachable(
    *,
    request: HtmxHttpRequest,
    blog: "Blog",
    is_paginated: bool = True,  # feed is not paginated
    post_queryset: QuerySet["Post"] | None = None,  # queryset is build from filterset / get_params if None
) -> dict:
    """
    Fetch all the data of a blog in a cachable (dict) format.
    """
    data: dict[str, Any] = {"blog": blog_to_dict(blog)}
    data = add_site_raw(data)
    data = add_root_nav_links(data)
    data["template_base_dir"] = blog.get_template_base_dir(request)

    # filters and pagination
    if is_paginated:
        get_params = request.GET.copy()
        filterset = blog.get_filterset(get_params)
        data["filterset"] = {"get_params": get_params.dict()}
        date_facet_choices = [(k, v) for k, v in filterset.form.fields["date_facets"].choices if k != ""]
        data["filterset"]["date_facets_choices"] = date_facet_choices
        data["filterset"]["category_facets_choices"] = get_facet_choices(filterset.form.fields, "category_facets")
        data["filterset"]["tag_facets_choices"] = get_facet_choices(filterset.form.fields, "tag_facets")
        data["pagination_context"] = blog.get_pagination_context(blog.get_published_posts(filterset.qs), get_params)
    # queryset data
    if post_queryset is None:
        post_queryset = data["pagination_context"]["object_list"]
        del data["pagination_context"]["object_list"]  # not cachable
    queryset_data = QuerysetData.create_from_post_queryset(
        request=request, site=Site(**data["site"]), queryset=post_queryset, is_podcast=blog.is_podcast
    )
    data = add_queryset_data(data, queryset_data)

    # page_url by id
    page_url_by_id: PageUrlByID = {}
    absolute_page_url_by_id: PageUrlByID = {}
    for post in queryset_data.queryset:
        page_url_by_id[post.pk] = post.get_url(request=request, current_site=Site(**data["site"]))
        absolute_page_url_by_id[post.pk] = post.full_url
    data["page_url_by_id"] = page_url_by_id
    data["absolute_page_url_by_id"] = absolute_page_url_by_id
    return data


class FeedRepository:
    def __init__(
        self,
        *,  # no positional arguments
        template_base_dir: str = "bootstrap4",
        site: Site,
        blog: "Blog",
        blog_url: str,
        queryset_data: QuerysetData,
        root_nav_links: LinkTuples,
        used: bool = False,
    ):
        self.site = site
        self.blog = blog
        self.blog_url = blog_url
        self.template_base_dir = template_base_dir
        self.root_nav_links = root_nav_links
        self.queryset_data = queryset_data
        self.page_url_by_id = queryset_data.page_url_by_id
        self.absolute_page_url_by_id = queryset_data.absolute_page_url_by_id
        self.renditions_for_posts = queryset_data.renditions_for_posts
        self.images = queryset_data.images
        self.image_by_id = queryset_data.images
        self.post_by_id = queryset_data.post_by_id
        self.owner_username_by_id = queryset_data.owner_username_by_id
        self.has_audio_by_id = queryset_data.has_audio_by_id
        self.videos = queryset_data.videos
        self.audios = queryset_data.audios
        self.audios_by_post_id = queryset_data.audios_by_post_id
        self.used = used
        self.post_queryset = queryset_data.queryset

        for post_id, page_url in self.page_url_by_id.items():
            cache_page_url(post_id, page_url)

    @classmethod
    def create_from_django_models(
        cls,
        *,
        request: HttpRequest,
        blog: "Blog",
        template_base_dir: str = "bootstrap4",
        post_queryset: QuerySet["Post"],
    ) -> "FeedRepository":
        site = Site.find_for_request(request)
        queryset_data = QuerysetData.create_from_post_queryset(request=request, site=site, queryset=post_queryset)
        root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
        for post in queryset_data.queryset:
            media_lookup: dict[str, dict[int, Audio | Video | Image]] = {}
            for image_pk in queryset_data.images_by_post_id.get(post.pk, []):
                media_lookup.setdefault("image", {}).update({image_pk: queryset_data.images[image_pk]})
            for video_pk in queryset_data.videos_by_post_id.get(post.pk, []):
                media_lookup.setdefault("video", {}).update({video_pk: queryset_data.videos[video_pk]})
            for audio_pk in queryset_data.audios_by_post_id.get(post.pk, []):
                media_lookup.setdefault("audio", {}).update({audio_pk: queryset_data.audios[audio_pk]})
            post._media_lookup = media_lookup

        return cls(
            site=site,
            blog=blog,
            queryset_data=queryset_data,
            template_base_dir=template_base_dir,
            root_nav_links=root_nav_links,
            blog_url=blog.get_url(request=request, current_site=site),
        )

    @staticmethod
    def data_for_feed_cachable(
        *,
        request: HtmxHttpRequest,
        blog: "Blog",
        is_podcast: bool = False,
    ) -> dict:
        blog.refresh_from_db()  # sometimes the blog object is stale / maybe because of serialization? FIXME
        if is_podcast:
            from .pages import Episode

            post_queryset = (
                Episode.objects.live()
                .descendant_of(blog)
                .select_related("podcast_audio__transcript")
                .filter(podcast_audio__isnull=False)
                .order_by("-visible_date")
            )
        else:
            from .pages import Post

            post_queryset = Post.objects.live().descendant_of(blog).order_by("-visible_date")
        data = data_for_blog_cachable(request=request, blog=blog, post_queryset=post_queryset, is_paginated=False)
        data["blog_url"] = blog.get_url(request=request)
        return data

    @classmethod
    def create_from_cachable_data(
        cls,
        *,
        data: dict[str, Any],
    ) -> "FeedRepository":
        """
        This method recreates usable models from the cachable data.
        """
        from wagtail.images.models import Image

        from . import Audio, Blog, Episode, Post, Transcript, Video

        site = Site(**data["site"])
        blog = Blog(**data["blog"])
        template_base_dir = data["template_base_dir"]
        post_by_id = {}
        podcast_fields = ["podcast_audio", "block", "keywords", "explicit"]
        for post_pk, post_data in data["post_by_id"].items():
            is_podcast = any(field in post_data for field in podcast_fields)
            if "podcast_audio" in post_data:
                post_data["podcast_audio"] = Audio(**post_data["podcast_audio"])
            if is_podcast:
                post_by_id[post_pk] = Episode(**post_data)
            else:
                post_by_id[post_pk] = Post(**post_data)
        post_queryset = [post_by_id[post_pk] for post_pk in data["posts"]]
        audios = {audio_pk: Audio(**audio_data) for audio_pk, audio_data in data["audios"].items()}
        images = {image_pk: Image(**image_data) for image_pk, image_data in data["images"].items()}
        videos = {video_pk: Video(**video_data) for video_pk, video_data in data["videos"].items()}
        podcast_audios = {
            episode_pk: Audio(**audio_data)
            for episode_pk, audio_data in data.get("podcast_audio_by_episode_id", {}).items()
        }
        transcripts = {
            audio_pk: Transcript(**transcript_data)
            for audio_pk, transcript_data in data.get("transcripts", {}).items()
        }

        renditions_for_posts = deserialize_renditions(data["renditions_for_posts"])

        user_model = get_user_model()
        for post in post_queryset:
            media_lookup: dict[str, dict[int, Audio | Video | Image]] = {}
            for image_pk in data["images_by_post_id"].get(post.pk, []):
                media_lookup.setdefault("image", {}).update({image_pk: images[image_pk]})
            for video_pk in data["videos_by_post_id"].get(post.pk, []):
                media_lookup.setdefault("video", {}).update({video_pk: videos[video_pk]})
            for audio_pk in data["audios_by_post_id"].get(post.pk, []):
                media_lookup.setdefault("audio", {}).update({audio_pk: audios[audio_pk]})
            post._media_lookup = media_lookup
            post.owner = user_model(username=data["owner_username_by_id"][post.pk])
            post.page_url = data["page_url_by_id"][post.pk]

        queryset_data = QuerysetData(
            post_queryset=post_queryset,
            post_by_id=post_by_id,
            audios=audios,
            images=images,
            videos=videos,
            audios_by_post_id=data["audios_by_post_id"],
            podcast_audio_by_episode_id=podcast_audios,
            transcript_by_audio_id=transcripts,
            videos_by_post_id=data["videos_by_post_id"],
            images_by_post_id=data["images_by_post_id"],
            owner_username_by_id=data["owner_username_by_id"],
            has_audio_by_id=data["has_audio_by_id"],
            renditions_for_posts=renditions_for_posts,
            page_url_by_id=data["page_url_by_id"],
            absolute_page_url_by_id=data["absolute_page_url_by_id"],
            cover_by_post_id=data["cover_by_post_id"],
            cover_alt_by_post_id=data["cover_alt_by_post_id"],
        )
        root_nav_links = data["root_nav_links"]
        return cls(
            **{
                "site": site,
                "blog": blog,
                "blog_url": data["blog_url"],
                "template_base_dir": template_base_dir,
                "queryset_data": queryset_data,
                "root_nav_links": root_nav_links,
            }
        )

    def get_post_detail_repository(self, post: "Post") -> PostDetailRepository:
        post_id = post.id
        blog = self.blog
        return PostDetailRepository(
            post_id=post_id,
            template_base_dir=self.template_base_dir,
            blog=blog,
            root_nav_links=self.root_nav_links,
            comments_are_enabled=post.get_comments_are_enabled(blog),
            has_audio=self.has_audio_by_id[post_id],
            page_url=self.page_url_by_id[post_id],
            absolute_page_url=self.absolute_page_url_by_id[post_id],
            owner_username=self.owner_username_by_id[post_id],
            blog_url=self.blog_url,
            audio_by_id=self.audios,
            video_by_id=self.videos,
            image_by_id=self.images,
            renditions_for_posts=self.renditions_for_posts,
            cover_image_url=self.queryset_data.cover_by_post_id.get(post_id, ""),
            cover_alt_text=self.queryset_data.cover_alt_by_post_id.get(post_id, ""),
        )

    def get_episode_feed_detail_repository(self, episode: "Episode") -> EpisodeFeedRepository:
        episode_id = episode.id
        podcast_audio = self.queryset_data.podcast_audio_by_episode_id[episode_id]
        transcript = self.queryset_data.transcript_by_audio_id.get(podcast_audio.id, None)
        return EpisodeFeedRepository(
            podcast_audio=podcast_audio,
            transcript=transcript,
        )


class BlogIndexRepository:
    def __init__(
        self,
        *,
        template_base_dir: str,
        blog: "Blog",
        filterset: Any,
        queryset_data: QuerysetData,
        pagination_context: dict[str, Any],
        root_nav_links: LinkTuples,
        use_audio_player: bool = False,
    ):
        self.template_base_dir = template_base_dir
        self.blog = blog
        self.filterset = filterset
        self.pagination_context = pagination_context
        self.root_nav_links = root_nav_links
        self.use_audio_player = use_audio_player
        # queryset data
        self.queryset_data = queryset_data
        self.renditions_for_posts = queryset_data.renditions_for_posts
        self.images = queryset_data.images
        self.image_by_id = queryset_data.images
        self.post_by_id = queryset_data.post_by_id
        self.owner_username_by_id = queryset_data.owner_username_by_id
        self.has_audio_by_id = queryset_data.has_audio_by_id
        self.video_by_id = queryset_data.videos
        self.audio_by_id = queryset_data.audios
        self.audios_by_post_id = queryset_data.audios_by_post_id
        self.post_queryset = queryset_data.queryset
        self.page_url_by_id = queryset_data.page_url_by_id
        self.absolute_page_url_by_id = queryset_data.absolute_page_url_by_id

        for post_id, page_url in self.page_url_by_id.items():
            cache_page_url(post_id, page_url)

    @staticmethod
    def data_for_blog_index_cachable(
        *,
        request: HtmxHttpRequest,
        blog: "Blog",
    ) -> dict:
        return data_for_blog_cachable(request=request, blog=blog, is_paginated=True, post_queryset=None)

    @classmethod
    def create_from_cachable_data(
        cls,
        *,
        data: dict[str, Any],
    ) -> "BlogIndexRepository":
        """
        This method recreates usable models from the cachable data.
        """
        from wagtail.images.models import Image

        from . import Audio, Blog, Episode, Post, Video

        # site = Site(**data["site"])
        template_base_dir = data["template_base_dir"]

        post_by_id = {}
        for post_pk, post_data in data["post_by_id"].items():
            if "podcast_audio" in post_data:
                post_data["podcast_audio"] = Audio(**post_data["podcast_audio"])
                post_by_id[post_pk] = Episode(**post_data)
            else:
                post_by_id[post_pk] = Post(**post_data)
        post_queryset = [post_by_id[post_pk] for post_pk in data["posts"]]
        pagination_context = data["pagination_context"]
        pagination_context["object_list"] = post_queryset
        audios = {audio_pk: Audio(**audio_data) for audio_pk, audio_data in data["audios"].items()}
        images = {image_pk: Image(**image_data) for image_pk, image_data in data["images"].items()}
        videos = {video_pk: Video(**video_data) for video_pk, video_data in data["videos"].items()}

        renditions_for_posts = deserialize_renditions(data["renditions_for_posts"])

        user_model = get_user_model()
        use_audio_player = False
        for post in post_queryset:
            media_lookup: dict[str, dict[int, Audio | Video | Image]] = {}
            for image_pk in data["images_by_post_id"].get(post.pk, []):
                media_lookup.setdefault("image", {}).update({image_pk: images[image_pk]})
            for video_pk in data["videos_by_post_id"].get(post.pk, []):
                media_lookup.setdefault("video", {}).update({video_pk: videos[video_pk]})
            for audio_pk in data["audios_by_post_id"].get(post.pk, []):
                media_lookup.setdefault("audio", {}).update({audio_pk: audios[audio_pk]})
            post._media_lookup = media_lookup
            post.owner = user_model(username=data["owner_username_by_id"][post.pk])
            post.page_url = data["page_url_by_id"][post.pk]

            if data["has_audio_by_id"][post.pk]:
                use_audio_player = True

        queryset_data = QuerysetData(
            post_queryset=post_queryset,
            post_by_id=post_by_id,
            audios=audios,
            images=images,
            videos=videos,
            audios_by_post_id=data["audios_by_post_id"],
            podcast_audio_by_episode_id={},  # not needed for blog
            transcript_by_audio_id={},  # not needed for blog
            videos_by_post_id=data["videos_by_post_id"],
            images_by_post_id=data["images_by_post_id"],
            owner_username_by_id=data["owner_username_by_id"],
            has_audio_by_id=data["has_audio_by_id"],
            renditions_for_posts=renditions_for_posts,
            page_url_by_id=data["page_url_by_id"],
            absolute_page_url_by_id=data["absolute_page_url_by_id"],
            cover_by_post_id=data["cover_by_post_id"],
            cover_alt_by_post_id=data["cover_alt_by_post_id"],
        )
        root_nav_links = data["root_nav_links"]

        filterset = PostFilterset(data["filterset"]["get_params"])
        filterset.filters["date_facets"].set_field_choices(data["filterset"]["date_facets_choices"])
        filterset.filters["category_facets"].set_field_choices(data["filterset"]["category_facets_choices"])
        filterset.filters["tag_facets"].set_field_choices(data["filterset"]["tag_facets_choices"])
        delattr(filterset, "_form")

        return cls(
            **{
                # "site": site,
                "blog": Blog(**data["blog"]),
                "template_base_dir": template_base_dir,
                "filterset": filterset,
                "pagination_context": pagination_context,
                "queryset_data": queryset_data,
                "root_nav_links": root_nav_links,
                "use_audio_player": use_audio_player,
            }
        )

    @classmethod
    def create_from_django_models(cls, request: HtmxHttpRequest, blog: "Blog") -> "BlogIndexRepository":
        get_params = request.GET.copy()
        filterset = blog.get_filterset(get_params)
        pagination_context = blog.get_pagination_context(blog.get_published_posts(filterset.qs), get_params)
        use_audio_player = False
        for post in pagination_context["object_list"]:
            post.page_url = post.get_url(request)
            if post.has_audio:
                use_audio_player = True
        template_base_dir = blog.get_template_base_dir(request)
        root_nav_links = []
        site = blog.get_site()
        if site is not None:
            for page in site.root_page.get_children().live():
                root_nav_links.append((page.get_url(request), page.title))
        queryset_data = QuerysetData.create_from_post_queryset(
            request=request, site=site, queryset=pagination_context["object_list"]
        )
        return cls(
            blog=blog,
            filterset=filterset,
            pagination_context=pagination_context,
            template_base_dir=template_base_dir,
            use_audio_player=use_audio_player,
            root_nav_links=root_nav_links,
            queryset_data=queryset_data,
        )
