from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import json
import re
from html.parser import HTMLParser
from typing import Any, cast
from types import SimpleNamespace
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils import timezone
from django.utils.safestring import mark_safe
from PIL import Image as PilImage
from wagtail.images.models import Image
from wagtail.images.models import Rendition
from wagtail.models import Page, Site

from cast.devdata import (
    add_audio_to_body,
    add_gallery_to_body,
    add_image_to_body,
    add_video_to_body,
    create_audio,
    create_gallery,
    create_image,
    create_mp4_file,
    create_python_body,
    create_user,
    create_video,
)
from cast.filters import get_active_facets, has_active_filters
from cast.models import (
    Audio,
    Blog,
    Episode,
    Gallery,
    Podcast,
    Post,
    TemplateBaseDirectory,
    Transcript,
    Video,
    get_or_create_gallery,
    get_template_base_dir_choices,
)
from cast.models.image_renditions import (
    create_missing_renditions_for_images,
    create_missing_renditions_for_posts,
    get_obsolete_and_missing_rendition_strings,
)
from cast.models.repository import BlogIndexRepository
from .htmx_helpers import HtmxHttpRequest

STYLEGUIDE_BLOG_SLUG = "styleguide-blog"
STYLEGUIDE_PODCAST_SLUG = "styleguide-podcast"
STYLEGUIDE_POST_SLUG_PREFIX = "styleguide-post"
STYLEGUIDE_EPISODE_SLUG = "styleguide-episode-1"
STYLEGUIDE_USER_NAME = "styleguide"
STYLEGUIDE_FALLBACK_THEMES = ("bootstrap4", "plain")
STYLEGUIDE_USER_AGENT = "django-cast-styleguide/1.0"


@dataclass(frozen=True)
class StyleguideMedia:
    audio: Audio
    gallery: Gallery
    image: Image
    video: Video


@dataclass(frozen=True)
class StyleguideRemoteMedia:
    gallery_images: list[Image] | None
    gallery_blocks: list[str] | None
    cover_image: Image | None
    audio: Audio | None
    transcript_data: dict[str, Any] | None
    video_url: str | None
    video_poster_url: str | None


@dataclass(frozen=True)
class StyleguideRemoteFile:
    url: str


@dataclass(frozen=True)
class StyleguideRemoteVideo:
    original: StyleguideRemoteFile
    poster: StyleguideRemoteFile | None = None

    def get_mime_type(self) -> str:
        path = urlparse(self.original.url).path.lower()
        if "." in path:
            ext = path.rsplit(".", 1)[-1]
        else:
            ext = ""
        return {
            "mp4": "video/mp4",
            "mov": "video/quicktime",
            "avi": "video/x-msvideo",
        }.get(ext, "video/mp4")


@dataclass(frozen=True)
class StyleguideTheme:
    active: str
    requested: str | None
    warning: str | None
    choices: list[dict[str, str]]

    @property
    def active_label(self) -> str:
        for choice in self.choices:
            if choice["slug"] == self.active:
                return choice["name"]
        return self.active  # pragma: no cover

    @property
    def requested_label(self) -> str | None:
        if self.requested is None:
            return None
        for choice in self.choices:
            if choice["slug"] == self.requested:
                return choice["name"]
        return self.requested  # pragma: no cover


class StyleguideData:
    def __init__(
        self,
        *,
        blog: Blog,
        blog_repository: BlogIndexRepository,
        media: StyleguideMedia,
        galleries: list[Gallery],
        gallery_blocks: list[str] | None,
        posts: list[Post],
        podcast: Podcast,
        episode: Episode,
        podcast_repository: BlogIndexRepository,
        transcript: dict[str, Any],
        video_url: str | None = None,
        video_poster_url: str | None = None,
    ) -> None:
        self.blog = blog
        self.blog_repository = blog_repository
        self.media = media
        self.galleries = galleries
        self.gallery_blocks = gallery_blocks
        self.posts = posts
        self.podcast = podcast
        self.episode = episode
        self.podcast_repository = podcast_repository
        self.transcript = transcript
        self.video_url = video_url
        self.video_poster_url = video_poster_url


def styleguide(request: HtmxHttpRequest) -> HttpResponse:
    if not _styleguide_is_enabled():
        raise Http404("Styleguide disabled")

    theme = _resolve_styleguide_theme(request)
    styleguide_data = _build_styleguide_data(request)

    styleguide_sections_template = f"cast/{theme.active}/styleguide/sections.html"
    context: dict[str, Any] = {
        "template_base_dir": theme.active,
        "styleguide_theme_choices": theme.choices,
        "styleguide_active_theme": theme.active,
        "styleguide_active_theme_label": theme.active_label,
        "styleguide_requested_theme": theme.requested,
        "styleguide_requested_theme_label": theme.requested_label,
        "styleguide_warning": theme.warning,
        "styleguide_sections_template": styleguide_sections_template,
        "styleguide_query_params": _query_params_without_theme(request),
    }
    context.update(_styleguide_context(styleguide_data, request, theme.active))
    if theme.active == "vue":
        context["styleguide_vue_payload"] = _styleguide_vue_payload(request, theme, context)

    request.cast_site_template_base_dir = theme.active
    return render(request, f"cast/{theme.active}/styleguide/index.html", context)


def _styleguide_is_enabled() -> bool:
    return bool(getattr(settings, "CAST_ENABLE_STYLEGUIDE", False))


def _resolve_styleguide_theme(request: HtmxHttpRequest) -> StyleguideTheme:
    choices = [{"slug": slug, "name": name} for slug, name in get_template_base_dir_choices()]
    choice_slugs = {choice["slug"] for choice in choices}

    requested_theme = request.GET.get("theme")
    if requested_theme not in choice_slugs:
        requested_theme = None

    current_theme = requested_theme or _current_site_theme(request, choice_slugs)
    active_theme = current_theme
    warning = None

    if not _styleguide_template_exists(active_theme):
        fallback_theme = _find_fallback_theme(choice_slugs)
        if fallback_theme != active_theme:
            warning = f"Styleguide templates for '{active_theme}' were not found. Showing '{fallback_theme}' instead."
        active_theme = fallback_theme

    return StyleguideTheme(active=active_theme, requested=requested_theme, warning=warning, choices=choices)


def _current_site_theme(request: HtmxHttpRequest, available_themes: set[str]) -> str:
    if hasattr(request, "session"):
        session_theme = request.session.get("template_base_dir")
        if session_theme in available_themes:
            return session_theme
    try:
        theme = TemplateBaseDirectory.for_request(request).name
    except (TemplateBaseDirectory.DoesNotExist, IntegrityError):
        theme = None
    if theme in available_themes:
        return theme
    return _find_fallback_theme(available_themes)


def _styleguide_template_exists(theme_slug: str) -> bool:
    try:
        get_template(f"cast/{theme_slug}/styleguide/index.html")
    except TemplateDoesNotExist:
        return False
    return True


def _find_fallback_theme(available_themes: set[str]) -> str:
    for candidate in STYLEGUIDE_FALLBACK_THEMES:
        if candidate in available_themes and _styleguide_template_exists(candidate):
            return candidate
    for candidate in available_themes:
        if _styleguide_template_exists(candidate):
            return candidate
    raise Http404("No styleguide templates available")  # pragma: no cover


def _query_params_without_theme(request: HtmxHttpRequest) -> list[tuple[str, str]]:
    return [(key, str(value)) for key, value in request.GET.items() if key != "theme"]


def _build_styleguide_data(request: HtmxHttpRequest) -> StyleguideData:
    site = _ensure_site()
    user = create_user(name=STYLEGUIDE_USER_NAME, password=STYLEGUIDE_USER_NAME)

    blog = _ensure_blog(site, user)
    remote_media = _fetch_styleguide_remote_media(user)
    galleries = _create_styleguide_galleries(remote_media.gallery_images, user)
    media = _create_styleguide_media(
        audio=remote_media.audio,
        gallery=galleries[0] if galleries else None,
        gallery_images=remote_media.gallery_images,
        user=user,
    )
    include_video_in_body = False
    posts = _ensure_posts(blog, user, media, galleries, include_video_in_body=include_video_in_body)
    _ensure_styleguide_tags_and_categories(posts)
    blog_repository = BlogIndexRepository.create_from_django_models(request, blog)

    podcast = _ensure_podcast(site, user)
    episode, transcript = _ensure_episode(
        podcast,
        user,
        media,
        galleries,
        remote_media.transcript_data,
        include_video_in_body=include_video_in_body,
    )
    _ensure_podlove_transcript(media.audio, transcript)
    podcast_repository = BlogIndexRepository.create_from_django_models(request, podcast)
    if posts:
        for post in posts:
            _ensure_styleguide_comments(post, site=site, user=user)
    cover_image = remote_media.cover_image or media.image
    _apply_styleguide_cover_images(
        blog=blog,
        podcast=podcast,
        posts=posts,
        episode=episode,
        image=cover_image,
    )

    return StyleguideData(
        blog=blog,
        blog_repository=blog_repository,
        media=media,
        galleries=galleries,
        gallery_blocks=remote_media.gallery_blocks,
        posts=posts,
        podcast=podcast,
        episode=episode,
        podcast_repository=podcast_repository,
        transcript=transcript,
        video_url=remote_media.video_url,
        video_poster_url=remote_media.video_poster_url,
    )


def _ensure_site() -> Site:
    site = Site.objects.first()
    if site is not None:
        return site
    root_page = Page.get_first_root_node()
    return Site.objects.create(hostname="localhost", port=80, root_page=root_page, is_default_site=True)


def _ensure_blog(site: Site, user) -> Blog:
    default_theme = _styleguide_default_theme()
    blog = Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).first()
    if blog is None:
        blog = Blog(
            title="Styleguide Blog",
            slug=STYLEGUIDE_BLOG_SLUG,
            owner=user,
            template_base_dir=default_theme,
        )
        site.root_page.add_child(instance=blog)
        blog = _ensure_live(blog)
    else:
        available = {slug for slug, _name in get_template_base_dir_choices()}
        if not blog.template_base_dir or blog.template_base_dir not in available:
            blog.template_base_dir = default_theme
            blog.save()
        blog = _ensure_live(blog)
    return blog


def _styleguide_post_date(now: datetime, months_back: int) -> datetime:
    """Return a datetime N calendar months before *now*, guaranteeing distinct months."""
    from dateutil.relativedelta import relativedelta

    return now - relativedelta(months=months_back)


def _ensure_posts(
    blog: Blog,
    user,
    media: StyleguideMedia,
    galleries: list[Gallery],
    *,
    include_video_in_body: bool,
) -> list[Post]:
    posts = []
    post_count = _styleguide_post_count()
    now = timezone.now()
    for index in range(1, post_count + 1):
        slug = f"{STYLEGUIDE_POST_SLUG_PREFIX}-{index}"
        post = Post.objects.child_of(blog).filter(slug=slug).first()
        include_media = index == 1
        body = _build_styleguide_body(
            media=media if include_media else None,
            include_media=include_media,
            galleries=galleries,
            include_video=include_video_in_body,
        )
        serialized_body = json.dumps(body)
        # Spread posts across different calendar months for rich date facets
        post_date = _styleguide_post_date(now, index - 1)
        if post is None:
            post = Post(
                title=f"Styleguide Post {index}",
                slug=slug,
                owner=user,
                body=serialized_body,
                visible_date=post_date,
                first_published_at=post_date,
            )
            blog.add_child(instance=post)
        else:
            needs_save = False
            if include_media and _styleguide_should_refresh_body(post, serialized_body):
                post.body = serialized_body
                needs_save = True
            if post.visible_date.strftime("%Y-%m") != post_date.strftime("%Y-%m"):
                post.visible_date = post_date
                needs_save = True
            if needs_save:
                post.save()
        post = _ensure_live(post)
        posts.append(Post.objects.get(pk=post.pk).specific)
    return posts


def _ensure_styleguide_tags_and_categories(posts: list[Post]) -> None:
    """Assign tags and categories to styleguide posts for rich filter facets."""
    from cast.models.snippets import PostCategory

    tag_names = ["python", "django", "wagtail", "tutorial"]
    category_data = [
        ("Today I Learned", "til"),
        ("WeekNotes", "weeknotes"),
    ]

    # Ensure categories exist
    categories = []
    for name, slug in category_data:
        cat, _ = PostCategory.objects.get_or_create(slug=slug, defaults={"name": name})
        categories.append(cat)

    for index, post in enumerate(posts):
        # Assign tags: first post gets 2 tags, others get 1 each (rotating)
        if index == 0:
            post.tags.add(tag_names[0], tag_names[1])
        else:
            post.tags.add(tag_names[index % len(tag_names)])
        # Assign categories: alternate between the two categories
        category = categories[index % len(categories)]
        if not post.categories.filter(pk=category.pk).exists():
            post.categories.add(category)
        post.save()


def _ensure_podcast(site: Site, user) -> Podcast:
    default_theme = _styleguide_default_theme()
    podcast = Podcast.objects.filter(slug=STYLEGUIDE_PODCAST_SLUG).first()
    if podcast is None:
        podcast = Podcast(
            title="Styleguide Podcast",
            slug=STYLEGUIDE_PODCAST_SLUG,
            owner=user,
            template_base_dir=default_theme,
        )
        site.root_page.add_child(instance=podcast)
        podcast = _ensure_live(podcast)
    else:
        available = {slug for slug, _name in get_template_base_dir_choices()}
        if not podcast.template_base_dir or podcast.template_base_dir not in available:
            podcast.template_base_dir = default_theme
            podcast.save()
        podcast = _ensure_live(podcast)
    return podcast


def _ensure_episode(
    podcast: Podcast,
    user,
    media: StyleguideMedia,
    galleries: list[Gallery],
    transcript_seed: dict[str, Any] | None,
    *,
    include_video_in_body: bool,
) -> tuple[Episode, dict[str, Any]]:
    transcript_seed = transcript_seed or _styleguide_transcript_data()
    if galleries and len(galleries) > 1:
        galleries_for_body = galleries[1:]
    else:
        galleries_for_body = galleries
    episode = Episode.objects.child_of(podcast).filter(slug=STYLEGUIDE_EPISODE_SLUG).first()
    if episode is None:
        audio = media.audio
        transcript_data = transcript_seed
        _ensure_podlove_transcript(audio, transcript_data)
        body = _build_styleguide_body(
            media=media,
            include_media=True,
            galleries=galleries_for_body or [media.gallery],
            include_video=include_video_in_body,
        )
        episode = Episode(
            title="Styleguide Episode",
            slug=STYLEGUIDE_EPISODE_SLUG,
            owner=user,
            body=json.dumps(body),
            podcast_audio=audio,
            first_published_at=timezone.now(),
        )
        podcast.add_child(instance=episode)
    else:
        episode = episode.specific
        audio = episode.podcast_audio
        if audio is None:
            audio = media.audio
            episode.podcast_audio = audio
            episode.save()
        serialized_body = json.dumps(
            _build_styleguide_body(
                media=media,
                include_media=True,
                galleries=galleries_for_body or [media.gallery],
                include_video=include_video_in_body,
            )
        )
        if _styleguide_should_refresh_body(episode, serialized_body):
            episode.body = serialized_body
            episode.save()
        transcript = _ensure_podlove_transcript(audio, transcript_seed)
        # Transcript may exist without podlove data; fall back to the seed payload for rendering.
        transcript_data = transcript.podlove_data or transcript_seed
    episode = _ensure_live(episode)
    return Episode.objects.get(pk=episode.pk).specific, transcript_data


def _ensure_cover_image(page: Page, image: Image, alt_text: str) -> None:
    if not hasattr(page, "cover_image"):
        return
    if getattr(page, "cover_image_id", None) == image.pk and getattr(page, "cover_alt_text", "") == alt_text:
        return
    page.cover_image = image
    page.cover_alt_text = alt_text
    page.save()


def _apply_styleguide_cover_images(
    *,
    blog: Blog,
    podcast: Podcast,
    posts: list[Post],
    episode: Episode,
    image: Image,
) -> None:
    alt_text = "Styleguide cover"
    _ensure_cover_image(blog, image, alt_text)
    _ensure_cover_image(podcast, image, alt_text)
    if posts:
        _ensure_cover_image(posts[0], image, alt_text)
    _ensure_cover_image(episode, image, alt_text)


def _ensure_live(page: Page) -> Page:
    if not page.live:
        page.save_revision().publish()
        page.refresh_from_db()
    return page.specific


def _styleguide_post_count() -> int:
    pagination_size = int(getattr(settings, "POST_LIST_PAGINATION", 5))
    return max(6, pagination_size + 1)


def _styleguide_default_theme() -> str:
    available = {slug for slug, _name in get_template_base_dir_choices()}
    return _find_fallback_theme(available)


def _create_styleguide_galleries(images: list[Image] | None, user) -> list[Gallery]:
    galleries: list[Gallery] = []
    if images:
        image_ids = [image.pk for image in images if image and image.pk]
        images_by_id = {image.pk: image for image in Image.objects.filter(pk__in=image_ids)}
        ordered_images = [images_by_id[image_id] for image_id in image_ids if image_id in images_by_id]
        chunk_size = int(getattr(settings, "CAST_STYLEGUIDE_GALLERY_CHUNK_SIZE", 6))
        for start in range(0, len(ordered_images), chunk_size):
            chunk = ordered_images[start : start + chunk_size]
            if not chunk:  # pragma: no cover
                continue
            gallery = get_or_create_gallery([image.pk for image in chunk]) or create_gallery(images=chunk)
            galleries.append(gallery)
    if not galleries:
        for _ in range(2):
            gallery_images = [create_image() for _ in range(4)]
            gallery = create_gallery(images=gallery_images)
            galleries.append(gallery)
    return galleries


def _styleguide_should_refresh_body(page: Page, serialized_body: str) -> bool:
    try:
        current_data = page.body.stream_data  # type: ignore[attr-defined]
    except Exception:
        return True
    try:
        desired_data = json.loads(serialized_body)
    except json.JSONDecodeError:
        return True
    return current_data != desired_data


def _create_styleguide_media(
    *,
    audio: Audio | None = None,
    gallery: Gallery | None = None,
    gallery_images: list[Image] | None = None,
    user=None,
) -> StyleguideMedia:
    if gallery is None:
        if gallery_images is None or len(gallery_images) == 0:
            gallery_images = [create_image() for _ in range(3)]
        image = gallery_images[0] if gallery_images else create_image()
        gallery = get_or_create_gallery([image.pk for image in gallery_images]) or create_gallery(
            images=gallery_images
        )
    else:
        image = gallery.images.first() or create_image()
    mp4_file = create_mp4_file(fixture_name="test_video.mp4")
    video = create_video(mp4_file=mp4_file, user=user)
    if audio is None:
        audio = create_audio(user=user, unique_filenames=True)
    return StyleguideMedia(
        audio=audio,
        gallery=gallery,
        image=image,
        video=video,
    )


def _build_styleguide_body(
    *,
    media: StyleguideMedia | None,
    include_media: bool,
    galleries: list[Gallery],
    include_video: bool = True,
) -> list[dict[str, Any]]:
    body = create_python_body()
    overview = body[0]["value"]
    overview.append({"type": "paragraph", "value": "<p>Sample paragraph text for layout preview.</p>"})
    overview.append({"type": "paragraph", "value": "<p>Paragraph before media blocks to show spacing.</p>"})
    overview.append(
        {
            "type": "paragraph",
            "value": "<p>Longer paragraph to test spacing between text and media. It should wrap across multiple lines so margins, line height, and rhythm become obvious in the layout. This is intentionally verbose, mimicking a real paragraph from a post where the text has enough length to show how it sits next to images and galleries, and whether the typography feels balanced.</p>",
        }
    )
    overview.append({"type": "code", "value": {"language": "python", "source": "print('hello styleguide')"}})
    overview.append(
        {
            "type": "code",
            "value": {"language": "javascript", "source": "console.log('hello styleguide');"},
        }
    )
    if include_media and media is not None:
        body = add_image_to_body(body=body, image=media.image)
        overview.append(
            {
                "type": "paragraph",
                "value": "<p>This is a deliberately long paragraph placed between the single image and the gallery to stress test spacing, typography, and line wrapping. It should run for several lines on a wide screen and even more on a phone, so the rhythm of the text becomes obvious and any awkward gaps between blocks are easy to spot. The goal is to simulate a realistic post where a paragraph might introduce a photo, then continue with a bit of context before the next set of images appears. As you read, notice whether the paragraph feels visually attached to the image above it or whether it drifts too far away, and whether the spacing below feels tight or generous. Look at how the line length behaves, where the words break, how the punctuation sits near the margins, and whether the paragraph feels balanced across the column. The copy is intentionally verbose to create a dense block that reveals subtle spacing problems, such as margins that are too small for comfortable reading or too large for a cohesive narrative. It also helps reveal whether the theme’s default paragraph spacing creates a clear transition from narrative text into a denser media cluster, and whether the overall pacing feels calm or jittery as the reader scrolls. If the layout feels uneven, this is the spot where you should see it first.</p>",
            }
        )
        galleries_to_render = (galleries or [media.gallery])[: _styleguide_body_gallery_limit()]
        for index, gallery in enumerate(galleries_to_render, start=1):
            body = add_gallery_to_body(body=body, gallery=gallery)
            overview.append(
                {
                    "type": "paragraph",
                    "value": f"<p>Paragraph after gallery {index} to surface spacing issues. This should be long enough to wrap and show how paragraphs flow after a media block in real posts. Add a few more sentences here to create real line breaks and to highlight whether the spacing between the gallery and the next text block feels too tight or too loose.</p>",
                }
            )
            overview.append(
                {
                    "type": "paragraph",
                    "value": "<p>Second paragraph after the gallery. It adds more vertical rhythm and helps spot spacing inconsistencies between consecutive text blocks. This one is deliberately long as well, simulating the kind of copy found in real posts, with enough length to force multiple lines and make the spacing between paragraphs easy to judge.</p>",
                }
            )
        body = add_audio_to_body(body=body, audio=media.audio)
        overview.append({"type": "paragraph", "value": "<p>Paragraph after audio for rhythm and balance.</p>"})
        if include_video:
            body = add_video_to_body(body=body, video=media.video)
            overview.append({"type": "paragraph", "value": "<p>Paragraph after video to show block separation.</p>"})

    detail = body[1]["value"]
    detail.append({"type": "paragraph", "value": "<p>Detail section content for long-form layouts.</p>"})
    return body


def _styleguide_transcript_data() -> dict[str, Any]:
    return {
        "version": 1,
        "transcripts": [
            {
                "start": "00:00:00.000",
                "end": "00:00:05.000",
                "speaker": "Host",
                "voice": "",
                "text": "Welcome to the styleguide transcript preview.",
            },
            {
                "start": "00:00:05.000",
                "end": "00:00:09.500",
                "speaker": "Guest",
                "voice": "",
                "text": "This snippet shows how transcript segments render.",
            },
        ],
    }


def _styleguide_transcript_excerpt(data: dict[str, Any]) -> dict[str, Any]:
    max_segments = int(getattr(settings, "CAST_STYLEGUIDE_TRANSCRIPT_EXCERPT_SEGMENTS", 2))
    transcripts = list(data.get("transcripts", []))
    return {**data, "transcripts": transcripts[:max_segments]}


def _styleguide_body_gallery_limit() -> int:
    return int(getattr(settings, "CAST_STYLEGUIDE_BODY_GALLERY_LIMIT", 1))


def _ensure_podlove_transcript(audio: Audio, data: dict[str, Any]) -> Transcript:
    transcript = Transcript.objects.filter(audio=audio).first()
    if transcript is None:
        transcript = Transcript.objects.create(audio=audio)
    if not transcript.podlove or transcript.podlove_data != data:
        podlove_content = json.dumps(data, indent=2)
        transcript.podlove.save("podlove.json", ContentFile(podlove_content))
        transcript.save()
    return transcript


def _render_gallery_block(
    *,
    images: list[Image],
    repository: BlogIndexRepository,
    template_base_dir: str,
    ensure_renditions: bool | None = None,
) -> str:
    from cast.blocks import GalleryBlockWithLayout

    if ensure_renditions is None:
        ensure_renditions = _styleguide_generate_renditions()
    gallery_repository = _styleguide_gallery_repository(
        repository,
        images,
        ensure_renditions=ensure_renditions,
    )
    block = GalleryBlockWithLayout()
    value = {"layout": "default", "gallery": images}
    html = block.render(value, context={"repository": gallery_repository, "template_base_dir": template_base_dir})
    return mark_safe(html)


def _ensure_styleguide_comments(post: Post, *, site: Site, user: User) -> None:
    if not post.get_comments_are_enabled(post.blog):
        return

    from django_comments import get_model as get_comment_model
    from django.contrib.sites.models import Site as DjangoSite

    comment_model = get_comment_model()
    ctype = ContentType.objects.get_for_model(post)
    site_id = getattr(settings, "SITE_ID", 1) or 1
    domain = getattr(site, "hostname", None) or "localhost"
    django_site, _created = DjangoSite.objects.get_or_create(
        id=site_id,
        defaults={"domain": domain, "name": domain},
    )

    field_names = {field.name for field in comment_model._meta.fields}
    parent_field = None
    if "parent" in field_names:
        parent_field = "parent"
    elif "parent_id" in field_names:
        parent_field = "parent_id"
    parent_text = (
        "This is a seeded styleguide comment to preview spacing, tone, and typography. "
        "It is intentionally longer to mimic a real reader response and to reveal how comment blocks wrap "
        "and breathe across multiple lines. The extra sentences stress-test alignment, line height, and "
        "indentation in a way short blurbs never will, especially on narrow screens. Ideally, the rhythm "
        "feels relaxed without becoming sparse, and the visual weight of the metadata stays balanced with "
        "the body copy."
    )
    reply_text = (
        "Threaded reply to show hierarchy and indentation. "
        "It should look distinct from the parent while keeping a clear visual connection. "
        "This added line helps preview how replies stack when the text is not just a single sentence."
    )

    existing = (
        comment_model.objects.filter(content_type=ctype, object_pk=str(post.pk), user=user)
        .order_by("submit_date", "pk")
        .all()
    )
    existing_comments = list(existing[:5])
    if existing_comments:
        parent = existing_comments[0]
        parent_updates = []
        if getattr(parent, "comment", "") != parent_text:
            parent.comment = parent_text
            parent_updates.append("comment")
        if "is_public" in field_names and getattr(parent, "is_public", True) is False:
            parent.is_public = True
            parent_updates.append("is_public")
        if "is_removed" in field_names and getattr(parent, "is_removed", False) is True:
            parent.is_removed = False
            parent_updates.append("is_removed")
        if parent_updates:
            parent.save(update_fields=parent_updates)

        reply = None
        if parent_field:
            for candidate in existing_comments[1:]:
                candidate_parent = getattr(candidate, parent_field, None)
                if candidate_parent == parent or getattr(candidate_parent, "pk", None) == parent.pk:
                    reply = candidate
                    break
        elif len(existing_comments) > 1:
            reply = existing_comments[1]

        if reply is not None:
            reply_updates = []
            if getattr(reply, "comment", "") != reply_text:
                reply.comment = reply_text
                reply_updates.append("comment")
            if "is_public" in field_names and getattr(reply, "is_public", True) is False:
                reply.is_public = True
                reply_updates.append("is_public")
            if "is_removed" in field_names and getattr(reply, "is_removed", False) is True:
                reply.is_removed = False
                reply_updates.append("is_removed")
            if reply_updates:
                reply.save(update_fields=reply_updates)
        return

    base_kwargs = {
        "content_type": ctype,
        "object_pk": str(post.pk),
        "site": django_site,
        "user": user,
        "user_name": user.username,
        "user_email": f"{user.username}@example.com",
        "comment": parent_text,
        "submit_date": timezone.now(),
    }
    if "is_public" in field_names:
        base_kwargs["is_public"] = True
    if "is_removed" in field_names:
        base_kwargs["is_removed"] = False

    parent = comment_model.objects.create(**base_kwargs)

    if parent_field:
        reply_kwargs = dict(base_kwargs)
        reply_kwargs.update(
            {
                "comment": reply_text,
                "submit_date": timezone.now(),
            }
        )
        reply_kwargs[parent_field] = parent
        comment_model.objects.create(**reply_kwargs)


def _styleguide_gallery_repository(
    repository: BlogIndexRepository, images: list[Image], *, ensure_renditions: bool
) -> SimpleNamespace:
    if ensure_renditions:
        images_with_type = cast(Any, iter([("gallery", image) for image in images]))
        _, missing_renditions = get_obsolete_and_missing_rendition_strings(images_with_type)
        if missing_renditions:
            create_missing_renditions_for_images(missing_renditions)

    renditions_for_posts = dict(repository.renditions_for_posts)
    for image in images:
        renditions_for_posts[image.pk] = list(Rendition.objects.filter(image=image))

    return SimpleNamespace(renditions_for_posts=renditions_for_posts)


def _ensure_styleguide_gallery_blocks(
    blocks: list[str] | None,
    galleries: list[Gallery],
    repository: BlogIndexRepository,
    template_base_dir: str,
    minimum: int = 1,
    limit: int | None = None,
) -> list[str]:
    gallery_blocks = _filter_styleguide_gallery_blocks(blocks, template_base_dir)
    if not gallery_blocks:
        for gallery in galleries:
            gallery_blocks.append(
                _render_gallery_block(
                    images=list(gallery.images.all()),
                    repository=repository,
                    template_base_dir=template_base_dir,
                    ensure_renditions=True,
                )
            )
    if len(gallery_blocks) < minimum:
        for gallery in galleries:
            if len(gallery_blocks) >= minimum:
                break
            gallery_blocks.append(
                _render_gallery_block(
                    images=list(gallery.images.all()),
                    repository=repository,
                    template_base_dir=template_base_dir,
                    ensure_renditions=True,
                )
            )
    if limit is not None:
        return gallery_blocks[:limit]
    return gallery_blocks


def _filter_styleguide_gallery_blocks(blocks: list[str] | None, template_base_dir: str) -> list[str]:
    if not blocks:
        return []
    expected_tag = {
        "bootstrap4": "image-gallery-bs4",
        "bootstrap5": "image-gallery-bs5",
    }.get(template_base_dir)
    if not expected_tag:
        return []
    tag_pattern = re.compile(rf"<{expected_tag}[^>]*>", flags=re.I)
    return [block for block in blocks if tag_pattern.search(block)]


class _StyleguideImageParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            attr_map = {key: value for key, value in attrs}
            href = attr_map.get("href")
            if href and "cast-gallery-link" in (attr_map.get("class") or ""):
                self._add_url(href)
            return
        if tag.lower() != "img":
            return
        attr_map = {key: value for key, value in attrs}
        src = attr_map.get("src")
        if src:
            self._add_url(src)
        srcset = attr_map.get("srcset")
        if srcset:
            for item in srcset.split(","):
                candidate = item.strip().split(" ")[0]
                if candidate:
                    self._add_url(candidate)

    def _add_url(self, url: str) -> None:
        if url.startswith("data:"):
            return
        full_url = urljoin(self.page_url, url)
        self.urls.append(full_url)


class _StyleguideTranscriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.segments: list[dict[str, str]] = []
        self._segment_depth = 0
        self._segment_tag: str | None = None
        self._in_time = False
        self._in_text = False
        self._current_time: str | None = None
        self._current_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        attr_map = {key: value for key, value in attrs}
        classes = attr_map.get("class") or ""
        if tag_name in {"div", "section"} and "transcript-segment" in classes:
            self._segment_depth = 1
            self._segment_tag = tag_name
            self._current_time = None
            self._current_text_parts = []
            return
        if self._segment_depth > 0:
            if self._segment_tag and tag_name == self._segment_tag:
                self._segment_depth += 1
            elif tag_name == "time":
                self._in_time = True
            elif tag_name == "p" and "transcript-text" in classes:
                self._in_text = True

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if self._segment_depth == 0:
            return
        if self._segment_tag and tag_name == self._segment_tag:
            self._segment_depth -= 1
            if self._segment_depth == 0:
                text = " ".join(part for part in self._current_text_parts if part).strip()
                if text:
                    self.segments.append(
                        {
                            "start": self._current_time or "",
                            "end": "",
                            "speaker": "",
                            "voice": "",
                            "text": text,
                        }
                    )
                self._current_time = None
                self._current_text_parts = []
                self._segment_tag = None
            return
        if tag_name == "time":
            self._in_time = False
        if tag_name == "p":
            self._in_text = False

    def handle_data(self, data: str) -> None:
        if self._in_time:
            self._current_time = (self._current_time or "") + data.strip()
        if self._in_text:
            text = data.strip()
            if text:
                self._current_text_parts.append(text)


def _styleguide_remote_media_enabled() -> bool:
    return bool(getattr(settings, "CAST_STYLEGUIDE_REMOTE_MEDIA", False))


def _styleguide_setting_list(name: str) -> list[str]:
    value = getattr(settings, name, None)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value]
    return []


def _styleguide_image_source_urls() -> list[str]:
    return _styleguide_setting_list("CAST_STYLEGUIDE_IMAGE_SOURCE_URLS")


def _styleguide_podcast_source_url() -> str | None:
    url = getattr(settings, "CAST_STYLEGUIDE_PODCAST_SOURCE_URL", None)
    return str(url) if url else None


def _styleguide_transcript_source_url() -> str | None:
    url = getattr(settings, "CAST_STYLEGUIDE_TRANSCRIPT_SOURCE_URL", None)
    return str(url) if url else None


def _styleguide_video_source_url() -> str | None:
    url = getattr(settings, "CAST_STYLEGUIDE_VIDEO_SOURCE_URL", None)
    return str(url) if url else None


def _styleguide_remote_timeout() -> float:
    return float(getattr(settings, "CAST_STYLEGUIDE_REMOTE_TIMEOUT", 8))


def _styleguide_remote_image_limit() -> int:
    return int(getattr(settings, "CAST_STYLEGUIDE_IMAGE_LIMIT", 6))


def _styleguide_generate_renditions() -> bool:
    return bool(getattr(settings, "CAST_STYLEGUIDE_GENERATE_RENDITIONS", False))


def _styleguide_transcript_max_segments() -> int:
    return int(getattr(settings, "CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS", 12))


def _styleguide_request(url: str) -> Request:
    return Request(url, headers={"User-Agent": STYLEGUIDE_USER_AGENT})


def _fetch_remote_html(url: str) -> str | None:
    try:
        with urlopen(_styleguide_request(url), timeout=_styleguide_remote_timeout()) as response:
            return response.read().decode("utf-8", "ignore")
    except Exception:
        return None


def _extract_image_urls(html: str, page_url: str) -> list[str]:
    original_urls = _extract_original_image_urls(html, page_url)
    return original_urls


def _extract_gallery_blocks(html: str) -> list[str]:
    blocks: list[str] = []
    for pattern in (
        r"<image-gallery-bs5[^>]*>.*?</image-gallery-bs5>",
        r"<image-gallery-bs4[^>]*>.*?</image-gallery-bs4>",
    ):
        matches = re.findall(pattern, html, flags=re.S | re.I)
        blocks.extend(matches)
    return blocks


def _extract_video_data(html: str, page_url: str) -> tuple[str | None, str | None]:
    video_match = re.search(r"<video[^>]*>.*?</video>", html, flags=re.S | re.I)
    scope = video_match.group(0) if video_match else html
    source_match = re.search(r"<source[^>]*src=[\"']([^\"']+)[\"']", scope, flags=re.I)
    if source_match is None:
        source_match = re.search(r"https?://[^\"'\s>]+\.mp4[^\"'\s>]*", html, flags=re.I)
    if source_match is None:
        video_url = None
    elif source_match.lastindex:
        video_url = urljoin(page_url, source_match.group(1))
    else:
        video_url = urljoin(page_url, source_match.group(0))
    poster_match = re.search(r"poster=[\"']([^\"']+)[\"']", scope, flags=re.I)
    poster_url = urljoin(page_url, poster_match.group(1)) if poster_match else None
    return video_url, poster_url


def _extract_cover_image_url(html: str, page_url: str) -> str | None:
    meta_candidates = [
        ("property", "og:image"),
        ("name", "twitter:image"),
        ("property", "twitter:image"),
    ]
    for attr_name, attr_value in meta_candidates:
        attr_pattern = re.escape(attr_name)
        value_pattern = re.escape(attr_value)
        match = re.search(
            rf"<meta[^>]*{attr_pattern}=[\"']{value_pattern}[\"'][^>]*content=[\"']([^\"']+)[\"']",
            html,
            flags=re.I,
        )
        if match is None:
            match = re.search(
                rf"<meta[^>]*content=[\"']([^\"']+)[\"'][^>]*{attr_pattern}=[\"']{value_pattern}[\"']",
                html,
                flags=re.I,
            )
        if match:
            return urljoin(page_url, match.group(1))
    return None


def _is_styleguide_image_url(url: str) -> bool:
    allowed_exts = (".jpg", ".jpeg", ".png")
    if not any(ext in url.lower() for ext in allowed_exts):
        return False
    if "cloudfront.net/images/" in url or "cloudfront.net/original_images/" in url:
        return True
    return False


def _extract_original_image_urls(html: str, page_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for raw_url in re.findall(r"data-full=[\"']([^\"']+)[\"']", html, flags=re.I):
        full_url = urljoin(page_url, raw_url)
        if not _is_styleguide_image_url(full_url):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)

    for raw_url in re.findall(
        r"<a[^>]*class=[\"'][^\"']*cast-gallery-link[^\"']*[\"'][^>]*href=[\"']([^\"']+)[\"']",
        html,
        flags=re.I,
    ):
        full_url = urljoin(page_url, raw_url)
        if not _is_styleguide_image_url(full_url):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)

    for raw_url in re.findall(r"https?://[^\"\s>]+/original_images/[^\"\s>]+", html):
        if raw_url in seen:
            continue
        seen.add(raw_url)
        urls.append(raw_url)

    for raw_url in re.findall(r"//[^\"\s>]+/original_images/[^\"\s>]+", html):
        full_url = f"https:{raw_url}"
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)

    for raw_url in re.findall(r"/original_images/[^\"\s>]+", html):
        full_url = urljoin(page_url, raw_url)
        if full_url in seen:
            continue
        seen.add(full_url)
        urls.append(full_url)

    filtered: list[str] = []
    for full_url in urls:
        if not _is_styleguide_image_url(full_url):
            continue
        filtered.append(full_url)
    return filtered


def _pick_largest_width_urls(urls: list[str]) -> list[str]:
    width_pattern = re.compile(r"\.width-(\d+)")
    best_by_base: dict[str, tuple[int, str]] = {}
    for url in urls:
        match = width_pattern.search(url)
        if match is None:
            best_by_base.setdefault(url, (0, url))
            continue
        width = int(match.group(1))
        base = width_pattern.sub(".width-", url)
        current = best_by_base.get(base)
        if current is None or width > current[0]:
            best_by_base[base] = (width, url)
    return [entry[1] for entry in best_by_base.values()]


def _extract_audio_url(html: str) -> str | None:
    match = re.search(r"name=\"twitter:player:stream\" content=\"([^\"]+)\"", html)
    if match:
        return match.group(1)
    match = re.search(r"https?://[^\"\s>]+\.m4a", html)
    if match:
        return match.group(0)
    return None


def _extract_podlove_player_api_url(html: str, page_url: str) -> str | None:
    matches = re.findall(r"<podlove-player[^>]*data-url=[\"']([^\"']+)[\"']", html, flags=re.I)
    for match in matches:
        if "/api/audios/podlove/" in match:
            return urljoin(page_url, match)
    if matches:
        return urljoin(page_url, matches[0])
    return None


def _fetch_podlove_data(url: str) -> dict[str, Any] | None:
    try:
        with urlopen(_styleguide_request(url), timeout=_styleguide_remote_timeout()) as response:
            return json.loads(response.read().decode("utf-8", "ignore"))
    except Exception:
        return None


def _extract_transcript_data(html: str) -> dict[str, Any] | None:
    parser = _StyleguideTranscriptParser()
    parser.feed(html)
    segments = parser.segments[: _styleguide_transcript_max_segments()]
    if not segments:
        return None
    return {"version": 1, "transcripts": segments}


def _get_or_create_remote_image(url: str, user) -> Image | None:
    title = f"Styleguide source: {url}"
    existing = Image.objects.filter(title=title).first()
    if existing is not None:
        return existing
    try:
        with urlopen(_styleguide_request(url), timeout=_styleguide_remote_timeout()) as response:
            content = response.read()
    except Exception:
        return None
    try:
        with PilImage.open(BytesIO(content)) as pil_image:
            width, height = pil_image.size
    except Exception:
        return None
    filename = urlparse(url).path.rsplit("/", 1)[-1] or "styleguide-image.jpg"
    image = Image(title=title)
    image.file.save(filename, ContentFile(content), save=False)
    image.width = width
    image.height = height
    image.save()
    return image


def _get_or_create_remote_audio(url: str, user) -> Audio | None:
    title = f"Styleguide source: {url}"
    existing = Audio.objects.filter(title=title).first()
    if existing is not None:
        return existing
    try:
        with urlopen(_styleguide_request(url), timeout=_styleguide_remote_timeout()) as response:
            content = response.read()
    except Exception:
        return None
    filename = urlparse(url).path.rsplit("/", 1)[-1] or "styleguide-audio.m4a"
    audio = Audio(user=user, title=title)
    audio.m4a.save(filename, ContentFile(content), save=True)
    audio.save()
    return audio


def _fetch_styleguide_remote_media(user) -> StyleguideRemoteMedia:
    if not _styleguide_remote_media_enabled():
        return StyleguideRemoteMedia(
            gallery_images=None,
            gallery_blocks=None,
            cover_image=None,
            audio=None,
            transcript_data=None,
            video_url=None,
            video_poster_url=None,
        )

    gallery_images: list[Image] = []
    image_urls: list[str] = []
    gallery_blocks: list[str] = []
    cover_image: Image | None = None
    for page_url in _styleguide_image_source_urls():
        html = _fetch_remote_html(page_url)
        if html is None:
            continue
        image_urls.extend(_extract_image_urls(html, page_url))
        gallery_blocks.extend(_extract_gallery_blocks(html))

    for url in image_urls:
        if len(gallery_images) >= _styleguide_remote_image_limit():
            break
        image = _get_or_create_remote_image(url, user)
        if image is not None:
            gallery_images.append(image)

    video_url: str | None = None
    video_poster_url: str | None = None
    video_source_url = _styleguide_video_source_url()
    video_sources = [video_source_url] if video_source_url else _styleguide_image_source_urls()
    for page_url in video_sources:
        if not page_url:
            continue
        html = _fetch_remote_html(page_url)
        if html is None:
            continue
        candidate_url, candidate_poster = _extract_video_data(html, page_url)
        if candidate_url:
            video_url = candidate_url
            video_poster_url = candidate_poster
            break

    podcast_url = _styleguide_podcast_source_url()
    transcript_url = _styleguide_transcript_source_url()
    audio: Audio | None = None
    transcript_data: dict[str, Any] | None = None

    if podcast_url:
        html = _fetch_remote_html(podcast_url)
        if html is not None:
            audio_url = _extract_audio_url(html)
            if audio_url:
                audio = _get_or_create_remote_audio(audio_url, user)
            podlove_api_url = _extract_podlove_player_api_url(html, podcast_url)
            if podlove_api_url:
                podlove_data = _fetch_podlove_data(podlove_api_url)
                if podlove_data:
                    poster_url = podlove_data.get("show", {}).get("poster")
                    if poster_url:
                        cover_image = _get_or_create_remote_image(poster_url, user)
                    if transcript_data is None and podlove_data.get("transcripts"):
                        transcripts = list(podlove_data["transcripts"])[: _styleguide_transcript_max_segments()]
                        transcript_data = {
                            "version": podlove_data.get("version", 1),
                            "transcripts": transcripts,
                        }
            cover_url = _extract_cover_image_url(html, podcast_url)
            if cover_url and cover_image is None:
                cover_image = _get_or_create_remote_image(cover_url, user)
        if transcript_url is None:
            transcript_url = podcast_url.rstrip("/") + "/transcript/"

    if transcript_url:
        transcript_html = _fetch_remote_html(transcript_url)
        if transcript_html is not None:
            transcript_data = _extract_transcript_data(transcript_html)
            if cover_image is None:
                cover_url = _extract_cover_image_url(transcript_html, transcript_url)
                if cover_url:
                    cover_image = _get_or_create_remote_image(cover_url, user)

    return StyleguideRemoteMedia(
        gallery_images=gallery_images or None,
        gallery_blocks=gallery_blocks or None,
        cover_image=cover_image,
        audio=audio,
        transcript_data=transcript_data,
        video_url=video_url,
        video_poster_url=video_poster_url,
    )


def _styleguide_context(
    styleguide_data: StyleguideData, request: HtmxHttpRequest, template_base_dir: str
) -> dict[str, Any]:
    blog_repository = styleguide_data.blog_repository
    podcast_repository = styleguide_data.podcast_repository

    blog_repository.template_base_dir = template_base_dir
    podcast_repository.template_base_dir = template_base_dir

    pagination_context = blog_repository.pagination_context
    posts = styleguide_data.posts
    object_list = pagination_context.get("object_list") or posts
    media_post = _styleguide_find_media_post(posts, fallback=object_list[0])
    create_missing_renditions_for_posts(iter([media_post]))
    refreshed_renditions = Post.get_all_renditions_from_queryset([media_post])
    if refreshed_renditions:
        blog_repository.renditions_for_posts.update(refreshed_renditions)
    episode = styleguide_data.episode

    for page in [media_post, episode]:
        page.page_url = page.get_url(request=request) or page.url or "#"

    gallery_blocks = _ensure_styleguide_gallery_blocks(
        styleguide_data.gallery_blocks,
        styleguide_data.galleries,
        blog_repository,
        template_base_dir,
        minimum=1,
        limit=1,
    )
    if styleguide_data.video_url:
        styleguide_video: Video | StyleguideRemoteVideo = StyleguideRemoteVideo(
            original=StyleguideRemoteFile(styleguide_data.video_url),
            poster=StyleguideRemoteFile(styleguide_data.video_poster_url)
            if styleguide_data.video_poster_url
            else None,
        )
    else:
        styleguide_video = styleguide_data.media.video
    transcript_excerpt = _styleguide_transcript_excerpt(styleguide_data.transcript)
    gallery_gap_text = (
        "This paragraph exists to stress test spacing between media groups and long-form text in real posts. "
        "It should be long enough to wrap across multiple lines on both desktop and mobile layouts, revealing "
        "whether the vertical rhythm feels balanced, the line height is comfortable, and the margins above and "
        "below a gallery block are consistent. The wording is intentionally verbose, similar to what you might "
        "find in a reflective blog entry or a narrative weeknote, where several sentences flow without headings "
        "or visual breaks. As you read, pay attention to how the paragraph hugs the gallery above it, how the "
        "first line aligns with the content grid, and how the last line resolves before the next gallery begins. "
        "If the space feels cramped, the images will appear stuck to the text. If it feels too loose, the layout "
        "will seem disconnected and sluggish. This block should make those issues obvious. It also tests how "
        "paragraph spacing behaves after image-heavy sections, whether margin collapsing creates surprises, and "
        "whether typography choices hold up when the copy is not just a short caption but a full paragraph with "
        "multiple clauses, varied sentence lengths, and natural pauses. Keep an eye on the line wrapping and the "
        "overall pacing of the page as you scroll from this text down to the next gallery."
    )

    context = {
        "blog": styleguide_data.blog,
        "page": media_post,
        "podcast": styleguide_data.podcast,
        "posts": pagination_context.get("object_list", posts),
        "filterset": blog_repository.filterset,
        "parameters": styleguide_data.blog.get_other_get_params(request.GET),
        "repository": blog_repository,
        "root_nav_links": blog_repository.root_nav_links,
        "styleguide_media_post": media_post,
        "styleguide_media_repository": blog_repository,
        "styleguide_gallery_blocks": gallery_blocks,
        "styleguide_gallery_gap_text": gallery_gap_text,
        "styleguide_audio": styleguide_data.media.audio,
        "styleguide_video": styleguide_video,
        "styleguide_episode": episode,
        "styleguide_episode_repository": podcast_repository,
        "styleguide_transcript": styleguide_data.transcript,
        "styleguide_transcript_excerpt": transcript_excerpt,
        "styleguide_comments_enabled": media_post.get_comments_are_enabled(styleguide_data.blog),
        "styleguide_episode_transcript_url": episode.get_transcript_url(),
        "active_facets": get_active_facets(blog_repository.filterset, request),
        "has_active_filters": has_active_filters(blog_repository.filterset, request),
    }
    context.update(pagination_context)
    return context


def _styleguide_vue_payload(
    request: HtmxHttpRequest, theme: StyleguideTheme, context: dict[str, Any]
) -> dict[str, Any]:
    media_post = context.get("styleguide_media_post")
    episode = context.get("styleguide_episode")
    return {
        "styleguide_url": request.path,
        "theme_choices": theme.choices,
        "active_theme": theme.active,
        "active_label": theme.active_label,
        "warning": theme.warning,
        "query_params": _query_params_without_theme(request),
        "media_post_slug": getattr(media_post, "slug", ""),
        "episode_slug": getattr(episode, "slug", ""),
    }


def _styleguide_find_media_post(posts: list[Post], fallback: Post) -> Post:
    for candidate in posts:
        if (
            candidate.audios.exists()
            or candidate.galleries.exists()
            or candidate.images.exists()
            or candidate.videos.exists()
        ):
            return candidate
    return fallback
