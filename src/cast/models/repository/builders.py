from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from django.db import connection
from django.db.models import QuerySet
from django.http import HttpRequest
from wagtail.images.models import Image
from wagtail.models import Site

from ...views import HtmxHttpRequest
from .serialization import (
    audio_to_dict,
    blog_to_dict,
    episode_to_dict,
    image_to_dict,
    post_to_dict,
    serialize_renditions,
    transcript_to_dict,
    video_to_dict,
)
from .snapshot import QuerysetData
from .types import Choice, HasChoices, PageUrlByID

if TYPE_CHECKING:
    from cast.models import Blog, Post


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


def apply_cover_fallback(
    cover_image_url: str, cover_alt_text: str, blog_cover_image_url: str, blog_cover_alt_text: str
) -> tuple[str, str]:
    """Fall back to the blog's cover image when the post has none."""
    if cover_image_url == "" and blog_cover_image_url:
        return blog_cover_image_url, blog_cover_alt_text
    return cover_image_url, cover_alt_text


def get_facet_choices(fields: dict[str, HasChoices], field_name) -> list[Choice]:
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
        data["site"] = dict(zip(columns, row_tuple))
    return data


def add_root_nav_links(data: dict[str, Any]) -> dict:
    """Add top-level navigation links (root page children) to the data dict."""
    site = Site(**data["site"])
    root_nav_links = [(p.get_url(), p.title) for p in site.root_page.get_children().live()]
    data["root_nav_links"] = root_nav_links
    return data


def add_queryset_data(data: dict[str, Any], queryset_data: QuerysetData) -> dict:
    """Serialize a ``QuerysetData`` instance into the cachable data dict."""
    # posts
    from ..pages import Episode

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
    for audio_pk, transcript in queryset_data.transcript_by_audio_id.items():
        transcripts[audio_pk] = transcript_to_dict(transcript)

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
    blog_cover_image_url = ""
    if blog.cover_image is not None:
        blog_cover_image_url = cast(Image, blog.cover_image).file.url
    data["blog_cover_image_url"] = blog_cover_image_url
    data["blog_cover_alt_text"] = blog.cover_alt_text
    data = add_site_raw(data, request=request, blog=blog)
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
    last_build_date = None
    for post in queryset_data.queryset:
        last_build_date = post.visible_date
        break
    if last_build_date is not None:
        data["last_build_date"] = last_build_date

    # page_url by id
    page_url_by_id: PageUrlByID = {}
    absolute_page_url_by_id: PageUrlByID = {}
    for post in queryset_data.queryset:
        page_url_by_id[post.pk] = post.get_url(request=request, current_site=Site(**data["site"]))
        absolute_page_url_by_id[post.pk] = post.full_url
    data["page_url_by_id"] = page_url_by_id
    data["absolute_page_url_by_id"] = absolute_page_url_by_id
    return data
