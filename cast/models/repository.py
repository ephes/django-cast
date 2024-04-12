import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image, Rendition
from wagtail.models import Site
from wagtail.rich_text.pages import PageLinkHandler

from ..filters import PostFilterset
from ..views import HtmxHttpRequest

if TYPE_CHECKING:
    from cast.models import Audio, Blog, Post, Video


PostByID = dict[int, "Post"]
PageUrlByID = dict[int, str]
HasAudioByID = dict[int, bool]
AudiosByPostID = dict[int, set["Audio"]]
AudioById = dict[int, "Audio"]
VideosByPostID = dict[int, set["Video"]]
ImagesByPostID = dict[int, set["Image"]]
ImageById = dict[int, Image]
LinkTuples = list[tuple[str, str]]
RenditionsForPost = dict[int, list[Rendition]]
SerializedRenditions = dict[int, list[dict]]


class PostRepository:
    renditions_for_posts: RenditionsForPost
    image_by_id: ImageById
    blog: "Blog"
    post_queryset: QuerySet["Post"]
    template_base_dir: str


class EmptyRepository(PostRepository):
    """
    This can be used as a default repository.
    """

    def __init__(self):
        from cast.models import Blog, Post

        self.renditions_for_posts = {}
        self.image_by_id = {}
        self.blog = Blog()
        self.post_queryset = Post.objects.none()


class QuerysetData:
    """
    This class is a container for the data that is needed to render a list of posts
    and that only depends on the queryset of those posts.
    """

    registered_blocks: list[Any] = []

    def __init__(
        self,
        *,
        post_queryset: Any,  # FIXME: Post queryset or list[Post], but does not work
        post_by_id: PostByID,
        audios: dict[int, "Audio"],  # used in blocks
        images: ImageById,
        videos: dict[int, "Video"],
        audios_by_post_id: AudiosByPostID,
        videos_by_post_id: VideosByPostID,
        images_by_post_id: ImagesByPostID,
        owner_username_by_id: dict[int, str],
        has_audio_by_id: HasAudioByID,
        renditions_for_posts: RenditionsForPost,
    ):
        self.queryset = post_queryset
        self.post_by_id = post_by_id
        self.audios = audios
        self.images = images
        self.videos = videos
        self.audios_by_post_id = audios_by_post_id
        self.videos_by_post_id = videos_by_post_id
        self.images_by_post_id = images_by_post_id
        self.owner_username_by_id = owner_username_by_id
        self.has_audio_by_id = has_audio_by_id
        self.renditions_for_posts = renditions_for_posts
        self.patch_page_link_handler(self.post_by_id)
        self.set_queryset_data_for_blocks()

    @staticmethod
    def patch_page_link_handler(post_by_id):
        def build_cached_get_instance(page_cache):
            @classmethod  # noqa has to be classmethod to override the original
            def cached_get_instance(_cls, attrs):
                page_id = int(attrs["id"])
                if page_id in page_cache:
                    return page_cache[page_id]
                else:
                    return super(PageLinkHandler, _cls).get_instance(attrs).specific

            return cached_get_instance

        PageLinkHandler.get_instance = build_cached_get_instance(post_by_id)
        return PageLinkHandler

    @classmethod
    def register_block(cls, block: Any) -> None:
        cls.registered_blocks.append(block)

    def set_queryset_data_for_blocks(self):
        for block in self.registered_blocks:
            block.queryset_data = self

    @classmethod
    def unset_queryset_data_for_blocks(cls):
        for block in cls.registered_blocks:
            block.queryset_data = None

    @classmethod
    def create_from_post_queryset(cls, queryset: QuerySet["Post"]) -> "QuerysetData":
        queryset = queryset.select_related("owner")
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
        audios_by_post_id: AudiosByPostID = {}
        videos_by_post_id: VideosByPostID = {}
        images_by_post_id: ImagesByPostID = {}
        for post in queryset:
            post_by_id[post.pk] = post.specific
            owner_username_by_id[post.pk] = post.owner.username
            has_audio_by_id[post.pk] = post.has_audio
            for image_type, image in post.get_all_images():
                images[image.pk] = image
                images_by_post_id.setdefault(post.pk, set()).add(image.pk)
            for video in post.videos.all():
                videos[video.pk] = video
                videos_by_post_id.setdefault(post.pk, set()).add(video.pk)
            for audio in post.audios.all():
                audios[audio.pk] = audio
                audios_by_post_id.setdefault(post.pk, set()).add(audio.pk)

        from .pages import Post

        return cls(
            post_queryset=queryset,
            post_by_id=post_by_id,
            audios=audios,
            images=images,
            videos=videos,
            audios_by_post_id=audios_by_post_id,
            videos_by_post_id=videos_by_post_id,
            images_by_post_id=images_by_post_id,
            has_audio_by_id=has_audio_by_id,
            renditions_for_posts=Post.get_all_renditions_from_queryset(queryset),
            owner_username_by_id=owner_username_by_id,
        )


class PostDetailRepository:
    """
    This class is a container for the data that is needed to render a post detail page.
    """

    def __init__(
        self,
        *,
        template_base_dir: str,
        blog: "Blog",
        root_nav_links: LinkTuples,
        comments_are_enabled: bool,
        has_audio: bool,
        page_url: str,
        absolute_page_url: str,
        owner_username: str,
        blog_url: str,
    ):
        self.template_base_dir = template_base_dir
        self.blog = blog
        self.root_nav_links = root_nav_links
        self.comments_are_enabled = comments_are_enabled
        self.has_audio = has_audio
        self.page_url = page_url
        self.absolute_page_url = absolute_page_url
        self.owner_username = owner_username
        self.blog_url = blog_url


class PostRepositoryForFeed(PostRepository):
    def __init__(
        self,
        *,  # no positional arguments
        site: Site,
        blog: "Blog",
        blog_url: str,
        template_base_dir: str = "bootstrap4",
        queryset_data: QuerysetData,
        page_url_by_id: PageUrlByID,
        absolute_page_url_by_id: PageUrlByID,
        root_nav_links: LinkTuples,
    ):
        self.site = site
        self.blog = blog
        self.blog_url = blog_url
        self.template_base_dir = template_base_dir
        self.root_nav_links = root_nav_links
        self.page_url_by_id = page_url_by_id
        self.absolute_page_url_by_id = absolute_page_url_by_id
        self.queryset_data = queryset_data
        self.renditions_for_posts = queryset_data.renditions_for_posts
        self.images = queryset_data.images
        self.image_by_id = queryset_data.images
        self.post_by_id = queryset_data.post_by_id
        self.owner_username_by_id = queryset_data.owner_username_by_id
        self.has_audio_by_id = queryset_data.has_audio_by_id
        self.videos = queryset_data.videos
        self.audios = queryset_data.audios
        self.audios_by_post_id = queryset_data.audios_by_post_id
        self.post_queryset = queryset_data.queryset

    def __repr__(self):
        return (
            f"PostData(renditions_for_posts={len(self.renditions_for_posts)}, "
            f"template_base_dir={self.template_base_dir})"
        )

    @classmethod
    def create_from_post_queryset(
        cls,
        *,
        request: HttpRequest,
        site: Site | None = None,
        blog: "Blog",
        template_base_dir: str,
        post_queryset: QuerySet["Post"],
    ) -> "PostRepositoryForFeed":
        queryset_data = QuerysetData.create_from_post_queryset(post_queryset)
        if site is None:
            site = Site.find_for_request(request)
        root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
        page_url_by_id: PageUrlByID = {}
        absolute_page_url_by_id: PageUrlByID = {}
        for post in queryset_data.queryset:
            page_url_by_id[post.pk] = post.get_url(request=request, current_site=site)
            absolute_page_url_by_id[post.pk] = post.full_url

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
            page_url_by_id=page_url_by_id,
            absolute_page_url_by_id=absolute_page_url_by_id,
            blog_url=blog.get_url(request=request, current_site=site),
        )


def audio_to_dict(audio) -> dict:
    return {
        "pk": audio.pk,
        "duration": audio.duration,
        "title": audio.title,
        "subtitle": audio.subtitle,
        "data": audio.data,
        "m4a": audio.m4a.name,
        "mp3": audio.mp3.name,
        "oga": audio.oga.name,
        "opus": audio.opus.name,
    }


def video_to_dict(video) -> dict:
    return {
        "pk": video.pk,
        "title": video.title,
        "original": video.original.name,
        "poster": video.poster.name,
        "poster_seconds": video.poster_seconds,
    }


def post_to_dict(post):
    return {
        "pk": post.pk,
        "uuid": post.uuid,
        "title": post.title,
        "visible_date": post.visible_date,
        "comments_enabled": post.comments_enabled,
        "body": json.dumps(list(post.body.raw_data)),
    }


def image_to_dict(image):
    return {
        "pk": image.pk,
        "title": image.title,
        "file": image.file.name,
        "width": image.width,
        "height": image.height,
    }


def rendition_to_dict(rendition):
    return {
        "pk": rendition.pk,
        "filter_spec": rendition.filter_spec,
        "file": rendition.file.name,
        "width": rendition.width,
        "height": rendition.height,
    }


class BlogIndexRepository(PostRepository):
    def __init__(
        self,
        *,
        # site: Site,
        template_base_dir: str,
        filterset: Any,
        queryset_data: QuerysetData | None = None,
        pagination_context: dict[str, Any],
        root_nav_links: LinkTuples,
        use_audio_player: bool = False,
    ):
        # self.site = site
        self.template_base_dir = template_base_dir
        self.filterset = filterset
        self.pagination_context = pagination_context
        self.root_nav_links = root_nav_links
        self.use_audio_player = use_audio_player
        # queryset data
        self.queryset_data = queryset_data
        if queryset_data is not None:
            self.renditions_for_posts = queryset_data.renditions_for_posts
            self.images = queryset_data.images
            self.image_by_id = queryset_data.images
            self.post_by_id = queryset_data.post_by_id
            self.owner_username_by_id = queryset_data.owner_username_by_id
            self.has_audio_by_id = queryset_data.has_audio_by_id
            self.videos = queryset_data.videos
            self.audios = queryset_data.audios
            self.audios_by_post_id = queryset_data.audios_by_post_id
            self.post_queryset = queryset_data.queryset
        else:
            self.image_by_id = {}


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


class BlogIndexRepositoryRaw(BlogIndexRepository):
    @staticmethod
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

    @staticmethod
    def add_root_nav_links(data: dict[str, Any]) -> dict:
        site = Site(**data["site"])
        root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
        data["root_nav_links"] = root_nav_links
        return data

    @staticmethod
    def add_queryset_data(data: dict[str, Any], queryset_data: QuerysetData) -> dict:
        # posts
        post_by_id = {}
        for pk, post in queryset_data.post_by_id.items():
            post_by_id[pk] = post_to_dict(post)
        data["post_by_id"] = post_by_id

        # audios
        audios = {}
        for pk, audio in queryset_data.audios.items():
            audios[pk] = audio_to_dict(audio)
        data["audios"] = audios

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
        data["has_audio_by_id"] = queryset_data.has_audio_by_id
        data["owner_username_by_id"] = queryset_data.owner_username_by_id
        return data

    @staticmethod
    def data_for_blog_index_cachable(
        *,
        request: HtmxHttpRequest,
        blog: "Blog",
    ) -> dict:
        data: dict[str, Any] = {}
        data = BlogIndexRepositoryRaw.add_site_raw(data)
        data = BlogIndexRepositoryRaw.add_root_nav_links(data)
        data["template_base_dir"] = blog.get_template_base_dir(request)

        # filters and pagination
        get_params = request.GET.copy()
        filterset = blog.get_filterset(get_params)
        data["filterset"] = {"get_params": get_params.dict()}
        date_facet_choices = [(k, v) for k, v in filterset.form.fields["date_facets"].choices if k != ""]
        data["filterset"]["date_facets_choices"] = date_facet_choices
        data["filterset"]["category_facets_choices"] = get_facet_choices(filterset.form.fields, "category_facets")
        data["filterset"]["tag_facets_choices"] = get_facet_choices(filterset.form.fields, "tag_facets")
        data["pagination_context"] = blog.get_pagination_context(blog.get_published_posts(filterset.qs), get_params)
        # queryset data
        queryset = data["pagination_context"]["object_list"]
        del data["pagination_context"]["object_list"]  # not cachable
        QuerysetData.unset_queryset_data_for_blocks()
        queryset_data = QuerysetData.create_from_post_queryset(queryset)
        data = BlogIndexRepositoryRaw.add_queryset_data(data, queryset_data)

        # page_url by id
        page_url_by_id: PageUrlByID = {}
        absolute_page_url_by_id: PageUrlByID = {}
        for post in queryset_data.queryset:
            page_url_by_id[post.pk] = post.get_url(request=request, current_site=Site(**data["site"]))
            absolute_page_url_by_id[post.pk] = post.full_url
        data["page_url_by_id"] = page_url_by_id
        data["absolute_page_url_by_id"] = absolute_page_url_by_id
        return data

    @classmethod
    def create_from_cachable_data(
        cls,
        *,
        data: dict[str, Any],
    ) -> "BlogIndexRepositoryRaw":
        """
        This method recreates usable models from the cachable data.
        """
        from wagtail.images.models import Image

        from . import Audio, Post, Video

        # site = Site(**data["site"])
        template_base_dir = data["template_base_dir"]
        post_by_id = {post_pk: Post(**post_data) for post_pk, post_data in data["post_by_id"].items()}
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
            videos_by_post_id=data["videos_by_post_id"],
            images_by_post_id=data["images_by_post_id"],
            owner_username_by_id=data["owner_username_by_id"],
            has_audio_by_id=data["has_audio_by_id"],
            renditions_for_posts=renditions_for_posts,
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
                "template_base_dir": template_base_dir,
                "filterset": filterset,
                "pagination_context": pagination_context,
                "queryset_data": queryset_data,
                "root_nav_links": root_nav_links,
                "use_audio_player": use_audio_player,
            }
        )

    @staticmethod
    def data_for_blog_index(
        *,
        request: HtmxHttpRequest,
        blog: "Blog",
    ) -> dict:
        """This works, but the result is not cachable since it's not possible to pickle it."""
        site = Site.find_for_request(request)
        root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
        template_base_dir = blog.get_template_base_dir(request)
        get_params = request.GET.copy()
        filterset = blog.get_filterset(get_params)
        pagination_context = blog.get_pagination_context(blog.get_published_posts(filterset.qs), get_params)
        queryset = pagination_context["object_list"]
        queryset_data = QuerysetData.create_from_post_queryset(queryset)
        return {
            # "site": site,
            "template_base_dir": template_base_dir,
            "filterset": filterset,
            "pagination_context": pagination_context,
            "queryset_data": queryset_data,
            "root_nav_links": root_nav_links,
        }

    @classmethod
    def create_from_blog_index_request(
        cls,
        *,
        request: HtmxHttpRequest,
        blog: "Blog",
    ) -> "BlogIndexRepositoryRaw":
        return cls(**BlogIndexRepositoryRaw.data_for_blog_index(request=request, blog=blog))


class BlogIndexRepositorySimple(BlogIndexRepository):
    @classmethod
    def create_from_blog(cls, request: HtmxHttpRequest, blog: "Blog") -> "BlogIndexRepositorySimple":
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
        kwargs = {
            "filterset": filterset,
            "pagination_context": pagination_context,
            "template_base_dir": template_base_dir,
            "use_audio_player": use_audio_player,
            "root_nav_links": root_nav_links,
        }

        return cls(**kwargs)  # type: ignore
