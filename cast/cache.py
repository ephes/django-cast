from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image, Rendition
from wagtail.models import Site
from wagtail.rich_text.pages import PageLinkHandler

if TYPE_CHECKING:
    from cast.models import Audio, Blog, Post, Video


PostByID = dict[int, "Post"]
PageUrlByID = dict[int, str]
HasAudioByID = dict[int, bool]
AudiosByPostID = dict[int, dict[int, "Audio"]]
LinkTuples = list[tuple[str, str]]


class PostData:
    registered_blocks: list[Any] = []

    def __init__(
        self,
        *,  # no positional arguments
        site: Site,
        blog: "Blog",
        blog_url: str,
        template_base_dir: str = "bootstrap4",
        renditions_for_posts: dict[int, list[Rendition]],
        images: dict[int, Image],
        post_by_id: PostByID,
        root_nav_links: LinkTuples,
        has_audio_by_id: HasAudioByID,
        page_url_by_id: PageUrlByID,
        owner_username_by_id: dict[int, str],
        videos: dict[int, "Video"],
        audios: dict[int, "Audio"],
        audios_by_post_id: AudiosByPostID,
        post_queryset: QuerySet["Post"],
    ):
        self.site = site
        self.blog = blog
        self.blog_url = blog_url
        self.template_base_dir = template_base_dir
        self.renditions_for_posts = renditions_for_posts
        self.images = images
        self.post_by_id = post_by_id
        self.root_nav_links = root_nav_links
        self.has_audio_by_id = has_audio_by_id
        self.page_url_by_id = page_url_by_id
        self.owner_username_by_id = owner_username_by_id
        self.videos = videos
        self.audios = audios
        self.audios_by_post_id = audios_by_post_id
        self.post_queryset = post_queryset
        self.patch_page_link_handler(self.post_by_id)
        self.set_post_data_for_blocks()

    def __repr__(self):
        return (
            f"PostData(renditions_for_posts={len(self.renditions_for_posts)}, "
            f"template_base_dir={self.template_base_dir})"
        )

    @classmethod
    def register_block(cls, block: Any) -> None:
        cls.registered_blocks.append(block)

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

    def set_post_data_for_blocks(self):
        for block in self.registered_blocks:
            block.post_data = self

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
        queryset = post_queryset
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
        if site is None:
            site = Site.find_for_request(request)
        post_by_id = {p.pk: p for p in blog.unfiltered_published_posts}
        images, has_audio_by_id, page_url_by_id, owner_username_by_id, videos, audios = {}, {}, {}, {}, {}, {}
        audios_by_post_id: AudiosByPostID = {}
        for post in queryset:
            # post_by_id[post.pk] = post.specific
            page_url_by_id[post.pk] = post.get_url(request=request, current_site=site)
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

        renditions_for_posts = Post.get_all_renditions_from_queryset(queryset)
        root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
        return cls(
            site=site,
            blog=blog,
            renditions_for_posts=renditions_for_posts,
            template_base_dir=template_base_dir,
            images=images,
            post_by_id=post_by_id,
            root_nav_links=root_nav_links,
            has_audio_by_id=has_audio_by_id,
            page_url_by_id=page_url_by_id,
            blog_url=blog.get_url(request=request, current_site=site),
            owner_username_by_id=owner_username_by_id,
            videos=videos,
            audios=audios,
            post_queryset=post_queryset,
            audios_by_post_id=audios_by_post_id,
        )
