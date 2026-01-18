from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.utils import timezone
from wagtail.images.models import Image
from wagtail.models import Page, Site

from cast.devdata import (
    add_audio_to_body,
    add_gallery_to_body,
    add_image_to_body,
    add_video_to_body,
    create_audio,
    create_gallery,
    create_image,
    create_python_body,
    create_user,
    create_video,
)
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
    get_template_base_dir_choices,
)
from cast.models.repository import BlogIndexRepository
from .htmx_helpers import HtmxHttpRequest

STYLEGUIDE_BLOG_SLUG = "styleguide-blog"
STYLEGUIDE_PODCAST_SLUG = "styleguide-podcast"
STYLEGUIDE_POST_SLUG_PREFIX = "styleguide-post"
STYLEGUIDE_EPISODE_SLUG = "styleguide-episode-1"
STYLEGUIDE_USER_NAME = "styleguide"
STYLEGUIDE_FALLBACK_THEMES = ("bootstrap4", "plain")


@dataclass(frozen=True)
class StyleguideMedia:
    audio: Audio
    gallery: Gallery
    image: Image
    video: Video


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
        posts: list[Post],
        podcast: Podcast,
        episode: Episode,
        podcast_repository: BlogIndexRepository,
        transcript: dict[str, Any],
    ) -> None:
        self.blog = blog
        self.blog_repository = blog_repository
        self.posts = posts
        self.podcast = podcast
        self.episode = episode
        self.podcast_repository = podcast_repository
        self.transcript = transcript


def styleguide(request: HtmxHttpRequest) -> HttpResponse:
    if not _styleguide_is_enabled():
        raise Http404("Styleguide disabled")

    theme = _resolve_styleguide_theme(request)
    styleguide_data = _build_styleguide_data(request)

    styleguide_sections_template = f"cast/{theme.active}/styleguide/sections.html"
    context = {
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
    posts = _ensure_posts(blog, user)
    blog_repository = BlogIndexRepository.create_from_django_models(request, blog)

    podcast = _ensure_podcast(site, user)
    episode, transcript = _ensure_episode(podcast, user)
    podcast_repository = BlogIndexRepository.create_from_django_models(request, podcast)

    return StyleguideData(
        blog=blog,
        blog_repository=blog_repository,
        posts=posts,
        podcast=podcast,
        episode=episode,
        podcast_repository=podcast_repository,
        transcript=transcript,
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


def _ensure_posts(blog: Blog, user) -> list[Post]:
    posts = []
    post_count = _styleguide_post_count()
    for index in range(1, post_count + 1):
        slug = f"{STYLEGUIDE_POST_SLUG_PREFIX}-{index}"
        post = Post.objects.child_of(blog).filter(slug=slug).first()
        if post is None:
            include_media = index == 1
            media = _create_styleguide_media(user=user) if include_media else None
            body = _build_styleguide_body(media=media, include_media=include_media)
            post = Post(
                title=f"Styleguide Post {index}",
                slug=slug,
                owner=user,
                body=json.dumps(body),
                first_published_at=timezone.now(),
            )
            blog.add_child(instance=post)
        post = _ensure_live(post)
        posts.append(Post.objects.get(pk=post.pk).specific)
    return posts


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


def _ensure_episode(podcast: Podcast, user) -> tuple[Episode, dict[str, Any]]:
    episode = Episode.objects.child_of(podcast).filter(slug=STYLEGUIDE_EPISODE_SLUG).first()
    if episode is None:
        audio = create_audio(user=user, unique_filenames=True)
        media = _create_styleguide_media(audio=audio, user=user)
        transcript_data = _styleguide_transcript_data()
        _ensure_podlove_transcript(audio, transcript_data)
        body = _build_styleguide_body(media=media, include_media=True)
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
        transcript_seed = _styleguide_transcript_data()
        if audio is None:
            audio = create_audio(user=user, unique_filenames=True)
            episode.podcast_audio = audio
            episode.save()
        transcript = _ensure_podlove_transcript(audio, transcript_seed)
        # Transcript may exist without podlove data; fall back to the seed payload for rendering.
        transcript_data = transcript.podlove_data or transcript_seed
    episode = _ensure_live(episode)
    return Episode.objects.get(pk=episode.pk).specific, transcript_data


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


def _create_styleguide_media(audio: Audio | None = None, user=None) -> StyleguideMedia:
    image = create_image()
    gallery_images = [create_image() for _ in range(3)]
    gallery = create_gallery(images=gallery_images)
    video = create_video(user=user)
    if audio is None:
        audio = create_audio(user=user, unique_filenames=True)
    return StyleguideMedia(
        audio=audio,
        gallery=gallery,
        image=image,
        video=video,
    )


def _build_styleguide_body(*, media: StyleguideMedia | None, include_media: bool) -> list[dict[str, Any]]:
    body = create_python_body()
    overview = body[0]["value"]
    overview.append({"type": "paragraph", "value": "<p>Sample paragraph text for layout preview.</p>"})
    overview.append({"type": "code", "value": {"language": "python", "source": "print('hello styleguide')"}})
    if include_media and media is not None:
        body = add_image_to_body(body=body, image=media.image)
        body = add_gallery_to_body(body=body, gallery=media.gallery)
        body = add_audio_to_body(body=body, audio=media.audio)
        body = add_video_to_body(body=body, video=media.video)

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


def _ensure_podlove_transcript(audio: Audio, data: dict[str, Any]) -> Transcript:
    transcript = Transcript.objects.filter(audio=audio).first()
    if transcript is None:
        transcript = Transcript.objects.create(audio=audio)
    if not transcript.podlove:
        podlove_content = json.dumps(data, indent=2)
        transcript.podlove.save("podlove.json", ContentFile(podlove_content))
        transcript.save()
    return transcript


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
    media_post = object_list[0]
    episode = styleguide_data.episode

    for page in [media_post, episode]:
        page.page_url = page.get_url(request=request) or page.url or "#"

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
        "styleguide_episode": episode,
        "styleguide_episode_repository": podcast_repository,
        "styleguide_transcript": styleguide_data.transcript,
        "styleguide_comments_enabled": media_post.get_comments_are_enabled(styleguide_data.blog),
        "styleguide_episode_transcript_url": episode.get_transcript_url(),
    }
    context.update(pagination_context)
    return context
