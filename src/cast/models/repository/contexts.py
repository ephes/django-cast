from typing import TYPE_CHECKING, Any, Optional, cast

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image
from wagtail.models import Site

from ...filters import PostFilterset
from ...views import HtmxHttpRequest
from .builders import _blog_url_from_referer, apply_cover_fallback, data_for_blog_cachable
from .serialization import blog_from_data, deserialize_renditions
from .snapshot import QuerysetData, cache_page_url
from .types import AudioById, ImageById, LinkTuples, RenditionsForPost, VideoById

if TYPE_CHECKING:
    from cast.models import Audio, Blog, Episode, Post, Transcript, Video


class PostDetailRepository:
    """Container for data needed to render a single post detail page.

    Holds template directory, navigation links, comment settings, media
    lookups, renditions, and cover image data. Created either from live
    Django models (``create_from_django_models``) or derived from a
    ``FeedRepository`` via ``get_post_detail_repository``.
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
        """Build a ``PostDetailRepository`` from a live post and the current request."""
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
            blog_url=_blog_url_from_referer(request, blog.get_url(request=request)),
            cover_image_url=cover_image_url,
            cover_alt_text=post.cover_alt_text,
            audio_by_id=post.media_lookup.get("audio", {}),
            video_by_id=post.media_lookup.get("video", {}),
            image_by_id=image_by_id,
            renditions_for_posts=post.get_all_renditions_from_queryset([post]),
        )


class EpisodeFeedRepository:
    """Container for per-episode data in a podcast RSS feed.

    Holds the podcast audio file and its optional transcript, used when
    rendering ``<enclosure>`` and ``<podcast:transcript>`` elements.
    """

    def __init__(
        self,
        *,
        podcast_audio: "Audio",
        transcript: Optional["Transcript"],
    ) -> None:
        self.podcast_audio = podcast_audio
        self.transcript = transcript


class FeedRepository:
    """Container for data needed to render an RSS or Atom feed.

    Holds the blog, site, queryset data, and navigation links. Provides
    helpers to derive a ``PostDetailRepository`` or
    ``EpisodeFeedRepository`` for individual items in the feed.

    Can be constructed from live Django models
    (``create_from_django_models``) or from a previously serialized
    cachable dict (``create_from_cachable_data``).
    """

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
        """Build a ``FeedRepository`` from live Django models and a post queryset."""
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
            from ..pages import Episode

            post_queryset = (
                Episode.objects.live()
                .descendant_of(blog)
                .select_related("podcast_audio__transcript")
                .filter(podcast_audio__isnull=False)
                .order_by("-visible_date")
            )
        else:
            from ..pages import Post

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

        from .. import Audio, Episode, Post, Transcript, Video

        site = Site(**data["site"])
        blog = blog_from_data(data["blog"])
        if (last_build_date := data.get("last_build_date")) is not None:
            blog._last_build_date = last_build_date
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
        """Derive a ``PostDetailRepository`` for a single post from this feed's data."""
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
        """Derive an ``EpisodeFeedRepository`` for a single episode from this feed's data."""
        episode_id = episode.id
        podcast_audio = self.queryset_data.podcast_audio_by_episode_id[episode_id]
        transcript = self.queryset_data.transcript_by_audio_id.get(podcast_audio.id, None)
        return EpisodeFeedRepository(
            podcast_audio=podcast_audio,
            transcript=transcript,
        )


class BlogIndexRepository:
    """Container for data needed to render a paginated blog index page.

    Holds the blog, filterset (date/category/tag facets), pagination
    context, queryset data, and navigation links. Constructed either
    from live Django models (``create_from_django_models``) or from
    a cachable dict (``create_from_cachable_data``).
    """

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

        from .. import Audio, Episode, Post, Video

        # site = Site(**data["site"])
        template_base_dir = data["template_base_dir"]

        post_by_id = {}
        blog_cover_image_url = data.get("blog_cover_image_url", "")
        blog_cover_alt_text = data.get("blog_cover_alt_text", "")
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
            cover_image_url = data["cover_by_post_id"].get(post.pk, "")
            cover_alt_text = data["cover_alt_by_post_id"].get(post.pk, "")
            cover_image_url, cover_alt_text = apply_cover_fallback(
                cover_image_url, cover_alt_text, blog_cover_image_url, blog_cover_alt_text
            )
            post.cover_image_url = cover_image_url
            post.cover_alt_text_display = cover_alt_text

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

        blog = blog_from_data(data["blog"])
        if (last_build_date := data.get("last_build_date")) is not None:
            blog._last_build_date = last_build_date

        return cls(
            **{
                # "site": site,
                "blog": blog,
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
        """Build a ``BlogIndexRepository`` from a blog and the current request."""
        get_params = request.GET.copy()
        filterset = blog.get_filterset(get_params)
        pagination_context = blog.get_pagination_context(blog.get_published_posts(filterset.qs), get_params)
        use_audio_player = False
        blog_cover_context = blog.get_cover_image_context()
        for post in pagination_context["object_list"]:
            post.page_url = post.get_url(request)
            cover_image_url = ""
            if post.cover_image is not None:
                cover_image_url = cast(Image, post.cover_image).file.url
            cover_alt_text = post.cover_alt_text
            cover_image_url, cover_alt_text = apply_cover_fallback(
                cover_image_url,
                cover_alt_text,
                blog_cover_context["cover_image_url"],
                blog_cover_context["cover_alt_text"],
            )
            post.cover_image_url = cover_image_url
            post.cover_alt_text_display = cover_alt_text
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
