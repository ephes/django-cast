import json
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image, Rendition
from wagtail.models import Site
from wagtail.rich_text.pages import PageLinkHandler

from .views import HtmxHttpRequest

if TYPE_CHECKING:
    from cast.models import Audio, Blog, Post, Video


PostByID = dict[int, "Post"]
PageUrlByID = dict[int, str]
HasAudioByID = dict[int, bool]
AudiosByPostID = dict[int, set["Audio"]]
VideosByPostID = dict[int, set["Video"]]
ImagesByPostID = dict[int, set["Image"]]
LinkTuples = list[tuple[str, str]]


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
        audios: dict[int, "Audio"],
        images: dict[int, Image],
        videos: dict[int, "Video"],
        audios_by_post_id: AudiosByPostID,
        videos_by_post_id: VideosByPostID,
        images_by_post_id: ImagesByPostID,
        owner_username_by_id: dict[int, str],
        has_audio_by_id: HasAudioByID,
        renditions_for_posts: dict[int, list[Rendition]],
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
        self.set_post_data_for_blocks()

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

    def set_post_data_for_blocks(self):
        for block in self.registered_blocks:
            block.queryset_data = self

    @classmethod
    def unset_post_data_for_blocks(cls):
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

        from .models import Post

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


class PostData:
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
    ) -> "PostData":
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


def rendtition_to_dict(rendition):
    return {
        "pk": rendition.pk,
        "filter_spec": rendition.filter_spec,
        "file": rendition.file.name,
        "width": rendition.width,
        "height": rendition.height,
    }


class PagedPostData:
    def __init__(
        self,
        *,
        site: Site,
        template_base_dir: str,
        filterset: Any,
        theme_form: Any,
        queryset_data: QuerysetData,
        paginate_context: dict[str, Any],
        root_nav_links: LinkTuples,
    ):
        self.site = site
        self.template_base_dir = template_base_dir
        self.filterset = filterset
        self.paginate_context = paginate_context
        self.queryset_data = queryset_data
        self.theme_form = theme_form
        self.root_nav_links = root_nav_links
        self.renditions_for_posts = queryset_data.renditions_for_posts
        self.images = queryset_data.images
        self.post_by_id = queryset_data.post_by_id
        self.owner_username_by_id = queryset_data.owner_username_by_id
        self.has_audio_by_id = queryset_data.has_audio_by_id
        self.videos = queryset_data.videos
        self.audios = queryset_data.audios
        self.audios_by_post_id = queryset_data.audios_by_post_id
        self.post_queryset = queryset_data.queryset

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
        renditions = {}
        for post_pk, renditions_for_post in queryset_data.renditions_for_posts.items():
            renditions[post_pk] = [rendtition_to_dict(rendition) for rendition in renditions_for_post]
        data["renditions_for_post"] = renditions
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
        data = PagedPostData.add_site_raw(data)
        data = PagedPostData.add_root_nav_links(data)
        data["template_base_dir"] = blog.get_template_base_dir(request)
        data["theme_form"] = {"initial": {"template_base_dir": data["template_base_dir"], "next": request.path}}
        # filterset not yet implemented FIXME
        get_params = request.GET.copy()
        filterset = blog.get_filterset(get_params)
        paginate_context = blog.paginate_queryset({}, blog.get_published_posts(filterset.qs), get_params)
        queryset = paginate_context["page_obj"].object_list
        QuerysetData.unset_post_data_for_blocks()
        queryset_data = QuerysetData.create_from_post_queryset(queryset)
        data = PagedPostData.add_queryset_data(data, queryset_data)
        return data

    @classmethod
    def create_from_cachable_data(
        cls,
        *,
        data: dict[str, Any],
    ) -> "PagedPostData":
        """
        This method recreates usable models from the cachable data.
        """
        from wagtail.images.models import Image, Rendition

        from .forms import SelectThemeForm
        from .models import Audio, Post, Video

        site = Site(**data["site"])
        template_base_dir = data["template_base_dir"]
        filterset = None
        post_by_id = {post_pk: Post(**post_data) for post_pk, post_data in data["post_by_id"].items()}
        post_queryset = [post_by_id[post_pk] for post_pk in data["posts"]]
        paginate_context = {"object_list": post_queryset, "page_obj": {"number": 1, "paginator": {"num_pages": 1}}}
        audios = {audio_pk: Audio(**audio_data) for audio_pk, audio_data in data["audios"].items()}
        images = {image_pk: Image(**image_data) for image_pk, image_data in data["images"].items()}
        videos = {video_pk: Video(**video_data) for video_pk, video_data in data["videos"].items()}

        renditions_for_posts = {}
        for post_pk, renditions in data["renditions_for_post"].items():
            renditions_for_posts[post_pk] = [Rendition(**rendition_data) for rendition_data in renditions]

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
        theme_form = SelectThemeForm(**data["theme_form"])
        root_nav_links = data["root_nav_links"]

        return cls(
            **{
                "site": site,
                "template_base_dir": template_base_dir,
                "filterset": filterset,
                "paginate_context": paginate_context,
                "queryset_data": queryset_data,
                "theme_form": theme_form,
                "root_nav_links": root_nav_links,
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
        paginate_context = blog.paginate_queryset({}, blog.get_published_posts(filterset.qs), get_params)
        queryset = paginate_context["page_obj"].object_list
        queryset_data = QuerysetData.create_from_post_queryset(queryset)
        theme_form = blog.get_theme_form(request)
        return {
            "site": site,
            "template_base_dir": template_base_dir,
            "filterset": filterset,
            "paginate_context": paginate_context,
            "queryset_data": queryset_data,
            "theme_form": theme_form,
            "root_nav_links": root_nav_links,
        }

    @classmethod
    def create_from_blog_index_request(
        cls,
        *,
        request: HtmxHttpRequest,
        blog: "Blog",
    ) -> "PagedPostData":
        return cls(**PagedPostData.data_for_blog_index(request=request, blog=blog))
