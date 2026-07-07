from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from django.db import connection
from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image
from wagtail.models import Site

from .serialization import (
    serialize_audio,
    serialize_blog,
    serialize_episode,
    serialize_image,
    serialize_post,
    serialize_renditions,
    serialize_transcript,
    serialize_video,
)
from .snapshot import PostQuerySnapshot
from .types import (
    AudioById,
    AudiosByPostID,
    Choice,
    HasChoices,
    ImageById,
    ImagesByPostID,
    MediaLookup,
    VideoById,
    VideosByPostID,
)

if TYPE_CHECKING:
    from cast.http_types import HtmxHttpRequest
    from cast.models import Blog, Post

    from .types import CachableBlogData


def _blog_url_from_referer(request: HttpRequest, base_blog_url: str) -> str:
    """Return blog URL with pagination state preserved from the HTTP referer.

    If the referer points to the same blog on the same host and includes query
    parameters (e.g. ``?page=2``), the full path with query string is returned.
    Otherwise falls back to the plain blog URL.
    """
    referer = request.headers.get("referer", "")
    if not referer:
        return base_blog_url
    parsed = urlparse(referer)
    # Only use referer from the same host (prevent open redirect)
    if parsed.netloc and parsed.netloc != request.get_host():
        return base_blog_url
    # Normalize trailing slashes for comparison (e.g. /blog vs /blog/)
    if parsed.path.rstrip("/") == base_blog_url.rstrip("/") and parsed.query:
        return f"{base_blog_url}?{parsed.query}"
    return base_blog_url


def build_media_lookup(
    post_pk: int,
    *,
    images_by_post_id: ImagesByPostID,
    videos_by_post_id: VideosByPostID,
    audios_by_post_id: AudiosByPostID,
    images: ImageById,
    videos: VideoById,
    audios: AudioById,
) -> MediaLookup:
    """Rebuild a post's ``media_lookup`` from the snapshot's per-post id sets.

    Centralizes the audio/video/image lookup-rebuild loop shared by the feed and
    blog-index repositories (live models and cachable-data paths). Returns a fresh
    mapping keyed by ``"image"`` / ``"video"`` / ``"audio"``; keys are present only
    when the post has media of that kind, preserving the previous behavior.
    """
    media_lookup: MediaLookup = {}
    for image_pk in images_by_post_id.get(post_pk, ()):
        media_lookup.setdefault("image", {})[image_pk] = images[image_pk]
    for video_pk in videos_by_post_id.get(post_pk, ()):
        media_lookup.setdefault("video", {})[video_pk] = videos[video_pk]
    for audio_pk in audios_by_post_id.get(post_pk, ()):
        media_lookup.setdefault("audio", {})[audio_pk] = audios[audio_pk]
    return media_lookup


def apply_cover_fallback(
    cover_image_url: str, cover_alt_text: str, blog_cover_image_url: str, blog_cover_alt_text: str
) -> tuple[str, str]:
    """Fall back to the blog's cover image when the post has none."""
    if cover_image_url == "" and blog_cover_image_url:
        return blog_cover_image_url, blog_cover_alt_text
    return cover_image_url, cover_alt_text


def get_facet_choices(fields: dict[str, HasChoices], field_name: str) -> list[Choice]:
    """Return non-empty filter choices for a facet field, or an empty list."""
    if field_name in fields:
        return [(k, v) for k, v in fields[field_name].choices if k != ""]
    return []


def add_site_raw(data: dict[str, Any], *, request: HttpRequest | None = None, blog: "Blog | None" = None) -> dict:
    """Add the relevant Wagtail site as a raw dict, preferably request-scoped."""
    site = None
    if request is not None:
        site = Site.find_for_request(request)
    if site is None and blog is not None:
        site = blog.get_site()
    if site is not None:
        data["site"] = {
            "id": site.id,
            "hostname": site.hostname,
            "port": site.port,
            "site_name": site.site_name,
            "root_page_id": site.root_page_id,
            "is_default_site": site.is_default_site,
        }
        return data

    # Fallback for contexts where request/blog site resolution is not available.
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
        if row_tuple is not None:
            data["site"] = dict(zip(columns, row_tuple))
    return data


def add_root_nav_links(data: dict[str, Any]) -> dict:
    """Add top-level navigation links (root page children) to the data dict."""
    site = Site(**data["site"])
    root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
    data["root_nav_links"] = root_nav_links
    return data


def add_queryset_data(data: dict[str, Any], queryset_data: PostQuerySnapshot) -> dict:
    """Serialize a ``PostQuerySnapshot`` instance into the cachable data dict."""
    # posts
    from ..pages import Episode

    post_by_id = {}
    for pk, post in queryset_data.post_by_id.items():
        if isinstance(post, Episode):
            post_by_id[pk] = serialize_episode(post)
        else:
            post_by_id[pk] = serialize_post(post)
    data["post_by_id"] = post_by_id

    # audios
    audios = {}
    for pk, audio in queryset_data.audios.items():
        audios[pk] = serialize_audio(audio)
    data["audios"] = audios

    # transcripts
    transcripts = {}
    for audio_pk, transcript in queryset_data.transcript_by_audio_id.items():
        transcripts[audio_pk] = serialize_transcript(transcript)

    # videos
    videos = {}
    for pk, video in queryset_data.videos.items():
        videos[pk] = serialize_video(video)
    data["videos"] = videos

    # images
    images = {}
    for pk, image in queryset_data.images.items():
        images[pk] = serialize_image(image)
    data["images"] = images

    # renditions
    data["renditions_for_posts"] = serialize_renditions(queryset_data.renditions_for_posts)
    data["posts"] = [post.pk for post in queryset_data.queryset]

    data["images_by_post_id"] = queryset_data.images_by_post_id
    data["videos_by_post_id"] = queryset_data.videos_by_post_id
    data["audios_by_post_id"] = queryset_data.audios_by_post_id
    data["podcast_audio_by_episode_id"] = {
        episode_id: serialize_audio(audio) for episode_id, audio in queryset_data.podcast_audio_by_episode_id.items()
    }
    data["transcripts"] = transcripts
    data["chapters"] = queryset_data.chapters_by_audio_id
    data["cover_by_post_id"] = queryset_data.cover_by_post_id
    data["cover_alt_by_post_id"] = queryset_data.cover_alt_by_post_id
    data["has_audio_by_id"] = queryset_data.has_audio_by_id
    data["owner_username_by_id"] = queryset_data.owner_username_by_id
    data["page_url_by_id"] = queryset_data.page_url_by_id
    data["absolute_page_url_by_id"] = queryset_data.absolute_page_url_by_id
    return data


def data_for_blog_cachable(
    *,
    request: HttpRequest,
    blog: "Blog",
    is_paginated: bool = True,  # feed is not paginated
    post_queryset: QuerySet["Post"] | None = None,  # queryset is build from filterset / get_params if None
) -> "CachableBlogData":
    """
    Fetch all the data of a blog in a cachable (dict) format.
    """
    data: dict[str, Any] = {"blog": serialize_blog(blog)}
    blog_cover_image_url = ""
    if blog.cover_image is not None:
        blog_cover_image_url = cast(Image, blog.cover_image).file.url
    data["blog_cover_image_url"] = blog_cover_image_url
    data["blog_cover_alt_text"] = blog.cover_alt_text
    data = add_site_raw(data, request=request, blog=blog)
    data = add_root_nav_links(data)
    data["template_base_dir"] = blog.get_template_base_dir(cast("HtmxHttpRequest", request))

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
    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=request, site=Site(**data["site"]), queryset=post_queryset
    )
    data = add_queryset_data(data, queryset_data)
    visible_dates = [post.visible_date for post in queryset_data.queryset]
    if visible_dates:
        data["last_build_date"] = max(visible_dates)

    # The dict is assembled incrementally above; this cast names the completed
    # cache boundary so consumers (``create_from_cachable_data``) type-check.
    return cast("CachableBlogData", data)
