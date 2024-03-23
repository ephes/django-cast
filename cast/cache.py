from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image, Rendition
from wagtail.models import Site
from wagtail.rich_text.pages import PageLinkHandler

from cast.views import HtmxHttpRequest

if TYPE_CHECKING:
    from cast.models import Audio, Blog, Post, Video


PostByID = dict[int, "Post"]
PageUrlByID = dict[int, str]
HasAudioByID = dict[int, bool]
AudiosByPostID = dict[int, dict[int, "Audio"]]
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
        post_queryset: QuerySet["Post"],
        post_by_id: PostByID,
        audios: dict[int, "Audio"],
        images: dict[int, Image],
        videos: dict[int, "Video"],
        audios_by_post_id: AudiosByPostID,
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
        for post in queryset:
            post_by_id[post.pk] = post.specific
            owner_username_by_id[post.pk] = post.owner.username
            has_audio_by_id[post.pk] = post.has_audio
            for image_type, image in post.get_all_images():
                images[image.pk] = image
            for video in post.videos.all():
                videos[video.pk] = video
            for audio in post.audios.all():
                audios[audio.pk] = audio
                audios_by_post_id.setdefault(post.pk, {}).update({audio.pk: audio})

        from .models import Post

        return cls(
            post_queryset=queryset,
            post_by_id=post_by_id,
            audios=audios,
            images=images,
            videos=videos,
            audios_by_post_id=audios_by_post_id,
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


class PagedPostData:
    def __init__(
        self,
        *,
        site: Site,
        template_base_dir: str,
        # filterset: Any,
        theme_form: Any,
        queryset_data: QuerysetData,
        paginate_context: dict[str, Any],
        root_nav_links: LinkTuples,
    ):
        self.site = site
        self.template_base_dir = template_base_dir
        # self.filterset = filterset
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

    @classmethod
    def create_from_blog_index_request(
        cls,
        *,
        request: HtmxHttpRequest,
        blog: "Blog",
    ) -> "PagedPostData":
        site = Site.find_for_request(request)
        root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
        template_base_dir = blog.get_template_base_dir(request)
        get_params = request.GET.copy()
        filterset = blog.get_filterset(get_params)
        paginate_context = blog.paginate_queryset({}, blog.get_published_posts(filterset.qs), get_params)
        queryset = paginate_context["page_obj"].object_list
        queryset_data = QuerysetData.create_from_post_queryset(queryset)
        theme_form = blog.get_theme_form(request)
        return cls(
            site=site,
            queryset_data=queryset_data,
            # filterset=filterset,
            theme_form=theme_form,
            paginate_context=paginate_context,
            template_base_dir=template_base_dir,
            root_nav_links=root_nav_links,
        )
