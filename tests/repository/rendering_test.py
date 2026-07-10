# ruff: noqa: F401,F811,I001
"""
This file contains tests for the post data cache. Make sure
all queries happen in one place and there are no additional
queries when rendering posts.
"""

import json
import pickle
from contextvars import Context, copy_context
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import pytest
import sqlparse
import cast.models.repository as repository_module
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites import models as sites_models
from django.contrib.sites.models import Site as DjangoSite
from django.db import connection, reset_queries
from django.urls import reverse
from django.utils import timezone
from wagtail.images.models import Image, Rendition
from wagtail.models import Site as WagtailSite

from cast.devdata import create_post, create_python_body, create_transcript, generate_blog_with_media
from cast.feeds import LatestEntriesFeed, RssPodcastFeed
from cast.filters import PostFilterset
from cast.models import (
    Audio,
    Blog,
    Contributor,
    ContributorLink,
    Episode,
    EpisodeContributor,
    Podcast,
    Post,
    Season,
    Transcript,
    Video,
)
from cast.models.image_renditions import create_missing_renditions_for_posts
from cast.models.repository.builders import _blog_url_from_referer
from cast.models.repository import (
    BlogIndexContext,
    FeedContext,
    PostDetailContext,
    PostQuerySnapshot,
    add_queryset_data,
    add_site_raw,
    apply_cover_fallback,
    deserialize_audio,
    deserialize_episode,
    deserialize_image,
    deserialize_post,
    deserialize_season,
    deserialize_transcript,
    deserialize_video,
    deserialize_blog,
    deserialize_episode_contributor,
    data_for_blog_cachable,
    get_facet_choices,
    serialize_audio,
    serialize_blog,
    serialize_episode_contributor,
    serialize_episode,
    serialize_image,
    serialize_post,
    serialize_renditions,
    serialize_season,
    serialize_transcript,
    serialize_video,
)
from cast.wagtail_hooks import PageLinkHandlerWithCache
from tests.factories import EpisodeFactory

from tests.repository.helpers import (
    StubFile,
    blocker,
    blog_index_repository,
    feed_repository,
    post_detail_repository,
    queryset_data,
    show_queries,
)


@pytest.mark.django_db
def test_post_detail_blog_url_preserves_pagination_from_referer(rf, post_in_blog):
    """When navigating from a paginated blog index, the 'Return to blog' link should
    preserve the page parameter so the user returns to the same page."""
    post = post_in_blog
    blog = post.blog
    blog_url = blog.get_url()
    referer = f"http://testserver{blog_url}?page=3"
    request = rf.get(post.get_url(), HTTP_REFERER=referer)
    repository = PostDetailContext.create_from_django_models(request=request, post=post)
    assert repository.blog_url == f"{blog_url}?page=3"


@pytest.mark.django_db
def test_post_detail_blog_url_without_referer(rf, post_in_blog):
    """Without a referer, blog_url should be the plain blog URL."""
    post = post_in_blog
    blog = post.blog
    request = rf.get(post.get_url())
    repository = PostDetailContext.create_from_django_models(request=request, post=post)
    assert repository.blog_url == blog.get_url()


@pytest.mark.django_db
def test_render_post_detail_with_django_models_repository(rf, post_in_blog):
    """
    This test should just use the default repository and fetch all data from the database.
    """
    # Given a post with a gallery, an image, a video and an audio
    post = post_in_blog
    post_url = post.get_url()
    request = rf.get(post_url)
    repository = PostDetailContext.create_from_django_models(request=request, post=post)
    reset_queries()
    # When we render the post detail page
    # with connection.execute_wrapper(blocker):
    response = post.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    # Then the media should be rendered
    assert "web-player/embed.5.js" in html  # audio player because has_audio is True
    assert post.title in html
    assert repository.page_url in html
    assert repository.owner_username.capitalize() in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert '<section class="block-gallery">' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_blog_index_with_django_models_repository(rf, post_in_blog):
    # Given a blog with a post
    post = post_in_blog
    blog = post.blog
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())
    request.htmx = False
    # The blog index repository is created from django models
    repository = BlogIndexContext.create_from_django_models(request=request, blog=blog)
    # When we render the blog index
    reset_queries()
    response = blog.serve(request, repository=repository).render()
    # Then post data should be generated on the fly and the media should be rendered
    assert isinstance(response.context_data["repository"], BlogIndexContext)
    html = response.content.decode("utf-8")
    assert author_name in html
    assert post_detail_url in html
    assert response.context_data["is_paginated"] is False
    # Then the media should be rendered
    assert "web-player/embed.5.js" in html  # audio player because has_audio is True
    assert post.title in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert '<section class="block-gallery">' in html
    # And the database should not be hit
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_feed_with_django_models_repository(rf, post_in_blog):
    # Given a post in a blog having a feed
    post = post_in_blog
    blog = post.blog
    post_queryset = blog.unfiltered_published_posts
    repository = FeedContext.create_from_django_models(
        request=rf.get("/"), blog=blog, post_queryset=post_queryset, template_base_dir="bootstrap4"
    )
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": blog.slug})
    request = rf.get(feed_url)
    view = LatestEntriesFeed(repository=repository)
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site  # cache site to avoid db hit
    reset_queries()
    # When we render the feed
    # with connection.execute_wrapper(blocker):
    response = view(request, slug=blog.slug)
    html = response.content.decode("utf-8")
    # Then the post title should be rendered
    assert post.title in html
    # And the database should be hit
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_feed_context_create_from_django_models_handles_missing_request_site(rf, blog, mocker):
    request = rf.get("/feed/", HTTP_HOST="no-such-host.local")
    post_queryset = blog.unfiltered_published_posts.none()
    mocker.patch("cast.models.repository.contexts.Site.find_for_request", return_value=None)
    mocker.patch(
        "cast.models.repository.contexts.PostQuerySnapshot.create_from_post_queryset",
        return_value=queryset_data(post_queryset=[]),
    )

    repository = FeedContext.create_from_django_models(
        request=request, blog=blog, post_queryset=post_queryset, template_base_dir="bootstrap4"
    )

    assert repository.site is None
    assert repository.root_nav_links == []


# Test render post detail, blog index and blog feed with cachable data
# provided without hitting the database


class StubFile:
    def __init__(self, name):
        self.name = name
        self.url = f"/media/{name}"


@pytest.fixture
def post():
    body = create_python_body()
    body[0]["value"].append({"type": "audio", "value": 1})
    body[0]["value"].append({"type": "video", "value": 1})
    body[0]["value"].append({"type": "image", "value": 1})
    gallery_with_layout = {"layout": "default", "gallery": [{"id": 1, "type": "item", "value": 1}]}
    body[0]["value"].append({"id": 1, "type": "gallery", "value": gallery_with_layout})
    serialized_body = json.dumps(body)
    return Post(id=1, title="Some post", body=serialized_body)


@pytest.fixture
def renditions_for_post():
    return {
        1: [
            # image
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-1110", width=1110, height=200),
            Rendition(file=StubFile("foo.avif"), filter_spec="width-1110|format-avif", width=1110, height=200),
            # gallery
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-120", width=100, height=120),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-240", width=100, height=240),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-360", width=100, height=360),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-120|format-avif", width=100, height=200),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-240|format-avif", width=100, height=200),
            Rendition(file=StubFile("foo.jpg"), filter_spec="width-360|format-avif", width=100, height=200),
        ]
    }


def test_render_post_detail_without_hitting_the_database(rf, post, renditions_for_post):
    """
    Given a post with media which is not in the database. And a repository
    containing the media needed to render the post detail.

    When we render the post detail, then the media should be rendered and
    the database should not be hit.
    """

    repository = PostDetailContext(
        post_id=1,
        template_base_dir="bootstrap4",
        blog=Blog(id=1, title="Some blog"),
        root_nav_links=[("http://testserver/", "Home"), ("http://testserver/about/", "About")],
        comments_are_enabled=False,  # FIXME see #131
        has_audio=True,
        page_url="/some-post/",
        absolute_page_url="http://testserver/some-post/",
        owner_username="owner",
        blog_url="/some-blog/",
        cover_image_url="/media/foo.jpg",
        cover_alt_text="Cover alt text",
        audio_by_id={1: Audio(id=1, title="Some audio", collection=None)},
        video_by_id={1: Video(id=1, title="Some video", collection=None, original=StubFile("foo.mp4"))},
        image_by_id={
            1: Image(id=1, title="Some image", collection=None, file=StubFile("foo.jpg"), width=2000, height=1000)
        },
        renditions_for_posts=renditions_for_post,
    )
    request = rf.get("/some-post/")
    request.htmx = False
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = post.serve(request, repository=repository).render()
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert "web-player/embed.5.js" in html  # audio player because has_audio is True
    assert post.title in html
    assert repository.page_url in html
    assert repository.owner_username.capitalize() in html
    # This database-free repository fixture has no social rendition URL; do not
    # emit an unusable empty image or a detached alt tag.
    assert '<meta name="twitter:image"' not in html
    assert '<meta property="og:image"' not in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert "1110w" in html
    assert '<section class="block-gallery">' in html
    context = response.context_data
    assert context["template_base_dir"] == repository.template_base_dir
    assert context["blog"] == repository.blog
    assert context["root_nav_links"] == repository.root_nav_links
    assert context["comments_are_enabled"] == repository.comments_are_enabled
    assert context["page_url"] == repository.page_url
    assert context["page"].page_url == repository.page_url
    assert context["absolute_page_url"] == repository.absolute_page_url
    assert context["cover_image_url"] == repository.cover_image_url
    assert context["cover_alt_text"] == repository.cover_alt_text
    assert len(connection.queries) == 0


@pytest.fixture
def blog_data(post, renditions_for_post):
    post.pk = 1
    audio = Audio(id=1, title="Some audio", collection=None)
    video = Video(id=1, title="Some video", collection=None, original=StubFile("foo.mp4"))
    image = Image(id=1, title="Some image", collection=None, file=StubFile("foo.jpg"), width=2000, height=1000)
    serialized_renditions = serialize_renditions(renditions_for_post)
    data = {
        "template_base_dir": "bootstrap4",
        "blog": {"id": 1, "title": "Some blog", "slug": "some-blog"},
        "blog_cover_image_url": "",
        "blog_cover_alt_text": "",
        "post_by_id": {1: serialize_post(post)},
        "posts": [1],
        "pagination_context": {},
        "audios": {1: serialize_audio(audio)},
        "images": {1: serialize_image(image)},
        "videos": {1: serialize_video(video)},
        "images_by_post_id": {1: [1]},
        "videos_by_post_id": {1: [1]},
        "audios_by_post_id": {1: [1]},
        "cover_by_post_id": {},
        "cover_alt_by_post_id": {},
        "renditions_for_posts": serialized_renditions,
        "owner_username_by_id": {1: "owner"},
        "page_url_by_id": {1: "/some-post/"},
        "absolute_page_url_by_id": {1: "http://testserver/some-post/"},
        "has_audio_by_id": {1: True},
        "root_nav_links": [("http://testserver/", "Home"), ("http://testserver/about/", "About")],
        "filterset": {
            "get_params": {},
            "date_facets_choices": [],
            "category_facets_choices": [],
            "tag_facets_choices": [],
        },
    }
    return data


def test_render_blog_index_without_hitting_the_database(rf, blog_data):
    """
    Given a blog including a post with media which is not in the database. And a repository
    containing the media needed to render the blog index page.

    When we render the blog index page, then the media should be rendered and
    the database should not be hit.
    """
    data = blog_data
    reset_queries()
    # with connection.execute_wrapper(blocker):
    repository = BlogIndexContext.create_from_cachable_data(data=data)
    blog = repository.blog
    request = rf.get("/some-blog/")
    request.htmx = False
    # with connection.execute_wrapper(blocker):
    response = blog.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    assert "Owner" in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert "1110w" in html
    assert '<section class="block-gallery">' in html
    context = response.context_data
    assert context["template_base_dir"] == repository.template_base_dir
    assert context["root_nav_links"] == repository.root_nav_links
    assert len(connection.queries) == 0


def test_render_podcast_index_without_hitting_the_database(rf, blog_data):
    """
    Given a podcast including a post with media which is not in the database. And a repository
    containing the media needed to render the podcast index page.

    When we render the podcast index page, then the media should be rendered and
    the database should not be hit.
    """
    data = blog_data
    # add podcast_audio
    data["post_by_id"][1]["type"] = "episode"
    data["post_by_id"][1]["podcast_audio"] = data["audios"][1]
    reset_queries()
    # with connection.execute_wrapper(blocker):
    repository = BlogIndexContext.create_from_cachable_data(data=data)
    podcast = Podcast(id=1, title="Some podcast", slug="some-podcast")
    request = rf.get("/some-podcast/")
    request.htmx = False
    # with connection.execute_wrapper(blocker):
    response = podcast.serve(request, repository=repository).render()
    html = response.content.decode("utf-8")
    assert "Owner" in html
    assert "audio_1" in html
    assert "<video" in html
    assert '<section class="block-image">' in html
    assert "1110w" in html
    assert '<section class="block-gallery">' in html
    context = response.context_data
    assert context["template_base_dir"] == repository.template_base_dir
    assert context["root_nav_links"] == repository.root_nav_links
    assert len(connection.queries) == 0


def test_render_feed_without_hitting_the_database(rf, blog_data):
    """
    Given a blog including a post with media which is not in the database. And a repository
    containing the media needed to render the feed.

    When we render the blog feed, then the database should not be hit.
    """
    data = deepcopy(blog_data)
    data.update(
        {
            "site": {"id": 1},
            "blog": {"id": 1, "title": "Some blog", "slug": "some-blog"},
            "blog_url": "/some-blog/",
            "is_podcast": False,
        }
    )
    reset_queries()
    repository = FeedContext.create_from_cachable_data(data=data)
    feed_url = reverse("cast:latest_entries_feed", kwargs={"slug": "some-blog"})
    request = rf.get(feed_url)
    view = LatestEntriesFeed(repository=repository)
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site  # cache site to avoid db hit
    reset_queries()
    # When we render the feed
    # with connection.execute_wrapper(blocker):
    response = view(request, slug="some-blog")
    html = response.content.decode("utf-8")
    assert data["post_by_id"][1]["title"] in html
    # And the database should be hit
    assert len(connection.queries) == 0


# Render post detail from cachable data is still missing


@pytest.mark.django_db
def test_render_blog_index_with_data_from_cache_without_hitting_the_database(rf, settings):
    # Given a post with media in a blog
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=6)
    post = blog.unfiltered_published_posts.first()
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())
    request.htmx = False
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created

    # Set up the cache
    cachable_data = BlogIndexContext.data_for_blog_index_cachable(request=request, blog=blog)
    pickled = pickle.dumps(cachable_data)  # make sure it's really cachable by pickling it
    cachable_data = pickle.loads(pickled)
    repository = BlogIndexContext.create_from_cachable_data(data=cachable_data)

    # When we render the blog index
    # call this once without blocker to populate SITE_CACHE
    reset_queries()
    with connection.execute_wrapper(blocker):
        response = blog.serve(request, repository=repository).render()
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-image"' in html
    assert 'class="cast-gallery-modal"' in html
    assert 'class="block-video"' in html
    assert 'class="block-audio"' in html
    assert author_name in html
    assert post_detail_url in html
    assert response.context_data["is_paginated"] is True
    # And the database should not be hit
    show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_blog_feed_with_data_from_cache_without_hitting_the_database(rf, settings):
    # Given a post with media in a blog
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=6)
    post = blog.unfiltered_published_posts.first()
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())
    request.htmx = False
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created

    # Set up the cache
    cachable_data = FeedContext.data_for_feed_cachable(request=request, blog=blog)
    pickled = pickle.dumps(cachable_data)  # make sure it's really cachable by pickling it
    cachable_data = pickle.loads(pickled)
    repository = FeedContext.create_from_cachable_data(data=cachable_data)

    # When we render the blog index
    # call this once without blocker to populate SITE_CACHE
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = LatestEntriesFeed(repository=repository)(request, slug=blog.slug)
    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-image"' in html
    assert 'class="cast-gallery-modal"' in html
    assert 'class="block-video"' in html
    assert 'class="block-audio"' in html
    assert author_name in html
    assert post_detail_url in html
    # And the database should not be hit
    # show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_podcast_feed_with_data_from_cache_without_hitting_the_database(rf, settings):
    # Given a post with media in a blog
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    blog = generate_blog_with_media(number_of_posts=6, podcast=True)
    post = Episode.objects.live().descendant_of(blog).order_by("-visible_date").first()
    season = Season.objects.create(podcast=blog, number=2, name="Launch")
    post.episode_number = 7
    post.episode_type = Episode.EpisodeType.BONUS
    post.season = season
    post.save(update_fields=["episode_number", "episode_type", "season"])
    author_name = post.owner.username.capitalize()
    post_detail_url = post.get_url()
    request = rf.get(blog.get_url())

    request.htmx = False
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created
    # _ = post.serve(rf.get("/")).render()  # force renditions to be created
    create_missing_renditions_for_posts([post])  # force renditions to be created

    # Set up the cache
    cachable_data = FeedContext.data_for_feed_cachable(request=request, blog=blog, is_podcast=True)
    pickled = pickle.dumps(cachable_data)  # make sure it's really cachable by pickling it
    cachable_data = pickle.loads(pickled)
    repository = FeedContext.create_from_cachable_data(data=cachable_data)

    # When we render the blog index
    # call this once without blocker to populate SITE_CACHE
    reset_queries()
    # with connection.execute_wrapper(blocker):
    response = RssPodcastFeed(repository=repository)(request, slug=blog.slug, audio_format="mp3")

    # Then the media should be rendered
    html = response.content.decode("utf-8")
    assert 'class="cast-image"' in html
    assert 'class="cast-gallery-modal"' in html
    assert 'class="block-video"' in html
    assert 'class="block-audio"' in html
    assert "podcast:transcript" in html
    assert "<itunes:episode>7</itunes:episode>" in html
    assert "<itunes:season>2</itunes:season>" in html
    assert "<itunes:episodeType>bonus</itunes:episodeType>" in html
    assert "<podcast:episode>7</podcast:episode>" in html
    assert '<podcast:season name="Launch">2</podcast:season>' in html
    assert author_name in html
    assert post_detail_url in html
    # And the database should not be hit
    # show_queries(connection.queries)
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_podcast_feed_with_cached_episode_contributors(rf, settings, episode, image):
    settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
    contributor = Contributor.objects.create(display_name="Cached Guest", slug="cached-guest", avatar=image)
    link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/cached-guest",
        sort_order=0,
    )
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        link=link,
        sort_order=0,
    )
    request = rf.get(episode.podcast.get_url())
    request.htmx = False
    cachable_data = FeedContext.data_for_feed_cachable(request=request, blog=episode.podcast, is_podcast=True)
    pickled = pickle.dumps(cachable_data)
    cachable_data = pickle.loads(pickled)
    repository = FeedContext.create_from_cachable_data(data=cachable_data)
    feed_url = reverse("cast:podcast_feed_rss", kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"})
    request = rf.get(feed_url)
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site

    reset_queries()
    response = RssPodcastFeed(repository=repository)(request, slug=episode.podcast.slug, audio_format="m4a")

    html = response.content.decode("utf-8")
    root = ElementTree.fromstring(html)
    namespace = {"podcast": "https://podcastindex.org/namespace/1.0/"}
    [person] = root.findall(".//podcast:person", namespace)
    assert person.text == "Cached Guest"
    assert person.attrib["role"] == "guest"
    assert person.attrib["href"] == "https://example.com/cached-guest"
    assert person.attrib["img"].startswith("http://testserver/media/")
    assert "fill-80x80" in person.attrib["img"]
    assert len(connection.queries) == 0
    PageLinkHandlerWithCache.cache.clear()


@pytest.mark.django_db
def test_render_episode_detail_with_contributors_from_repository_without_hitting_database(rf, episode, image):
    contributor = Contributor.objects.create(display_name="Detail Guest", slug="detail-guest", avatar=image)
    link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/detail-guest",
        sort_order=0,
    )
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        link=link,
        sort_order=0,
    )
    host = Contributor.objects.create(display_name="Detail Host", slug="detail-host")
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=host,
        role=EpisodeContributor.ROLE_HOST,
        sort_order=1,
    )
    request = rf.get(episode.get_url())
    repository = PostDetailContext.create_from_django_models(request=request, post=episode)

    reset_queries()
    with connection.execute_wrapper(blocker):
        response = episode.serve(request, repository=repository).render()

    html = response.content.decode("utf-8")
    assert 'class="episode-contributors"' in html
    assert 'class="episode-contributors__list"' in html
    assert 'class="episode-contributors__item"' in html
    assert 'class="episode-contributors__identity episode-contributors__identity--link"' in html
    assert "Detail Guest" in html
    assert "Detail Host" in html
    assert "https://example.com/detail-guest" in html
    assert 'src="/media/' in html
    assert "fill-80x80" in html
    assert 'alt=""' in html
    assert 'width="40"' in html
    assert 'height="40"' in html
    assert "episode-contributors__avatar--placeholder" in html
    assert 'aria-hidden="true"' in html
    assert ">D</span>" in html
    assert 'class="episode-contributors__role">Guest</span>' in html
    assert 'class="episode-contributors__role">Host</span>' in html
    assert html.index("Detail Guest") < html.index("Detail Host")
    assert html.index('class="episode-contributors"') < html.index("in_all heading")
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_render_podcast_feed_from_django_models_with_contributors_without_hitting_database(rf, episode, image):
    for index in range(3):
        contributor = Contributor.objects.create(
            display_name=f"Feed Guest {index}",
            slug=f"feed-guest-{index}",
            avatar=image,
        )
        link = ContributorLink.objects.create(
            contributor=contributor,
            service=ContributorLink.SERVICE_WEBSITE,
            url=f"https://example.com/feed-guest-{index}",
            sort_order=0,
        )
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_GUEST,
            link=link,
            sort_order=index,
        )
    post_queryset = (
        Episode.objects.live()
        .descendant_of(episode.podcast)
        .select_related("podcast_audio__transcript")
        .filter(podcast_audio__isnull=False)
        .order_by("-visible_date")
    )
    repository = FeedContext.create_from_django_models(
        request=rf.get("/"),
        blog=episode.podcast,
        post_queryset=post_queryset,
        template_base_dir="bootstrap4",
    )
    feed_url = reverse("cast:podcast_feed_rss", kwargs={"slug": episode.podcast.slug, "audio_format": "m4a"})
    request = rf.get(feed_url)
    django_site = DjangoSite(domain="testserver", name="testserver")
    sites_models.SITE_CACHE[1] = django_site

    reset_queries()
    with connection.execute_wrapper(blocker):
        response = RssPodcastFeed(repository=repository)(request, slug=episode.podcast.slug, audio_format="m4a")

    html = response.content.decode("utf-8")
    assert "Feed Guest 0" in html
    assert "Feed Guest 1" in html
    assert "Feed Guest 2" in html
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_blog_index_snapshot_query_count_does_not_scale_for_mixed_base_post_queryset(rf, blog, site, audio, body):
    larger_blog = Blog(title="larger mixed blog", slug="larger-mixed-blog", owner=blog.owner)
    site.root_page.add_child(instance=larger_blog)

    def add_mixed_posts(target_blog, *, episode_count: int, post_count: int, slug_prefix: str) -> None:
        for index in range(episode_count):
            EpisodeFactory(
                owner=target_blog.owner,
                parent=target_blog,
                title=f"{slug_prefix} episode {index}",
                slug=f"{slug_prefix}-episode-{index}",
                podcast_audio=audio,
                body=body,
            )
        for index in range(post_count):
            create_post(blog=target_blog, body=body, num=index)

    add_mixed_posts(blog, episode_count=2, post_count=2, slug_prefix="small-mixed")
    add_mixed_posts(larger_blog, episode_count=5, post_count=2, slug_prefix="large-mixed")

    def count_snapshot_queries(target_blog: Blog) -> int:
        reset_queries()
        PostQuerySnapshot.create_from_post_queryset(
            request=rf.get("/"),
            site=site,
            queryset=target_blog.unfiltered_published_posts,
        )
        return len(connection.queries)

    small_count = count_snapshot_queries(blog)
    larger_count = count_snapshot_queries(larger_blog)

    assert larger_count == small_count


@pytest.mark.django_db
def test_post_queryset_snapshot_caches_episode_contributors_for_base_post_queryset(rf, episode):
    contributor = Contributor.objects.create(display_name="Mixed Feed Guest", slug="mixed-feed-guest")
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        sort_order=0,
    )
    post_queryset = Post.objects.live().descendant_of(episode.podcast).order_by("-visible_date")

    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=rf.get("/"),
        site=episode.podcast.get_site(),
        queryset=post_queryset,
    )
    snapshot_episode = queryset_data.post_by_id[episode.pk]

    reset_queries()
    with connection.execute_wrapper(blocker):
        assignments = snapshot_episode.visible_contributor_assignments

    assert [assignment.display_name for assignment in assignments] == ["Mixed Feed Guest"]
    assert len(connection.queries) == 0


@pytest.mark.django_db
def test_post_queryset_snapshot_primes_repeated_contributor_avatar_once(rf, episode, mocker):
    contributor = Contributor.objects.create(display_name="Repeat Guest", slug="repeat-guest")
    EpisodeContributor.objects.create(
        episode=episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        sort_order=0,
    )
    other_episode = EpisodeFactory(
        owner=episode.owner,
        parent=episode.podcast,
        title="other podcast episode",
        slug="other-podcast-entry",
        podcast_audio=episode.podcast_audio,
        body=episode.body,
    )
    EpisodeContributor.objects.create(
        episode=other_episode,
        contributor=contributor,
        role=EpisodeContributor.ROLE_GUEST,
        sort_order=0,
    )
    compute_avatar_rendition_url = mocker.patch(
        "cast.models.contributors.Contributor._compute_avatar_rendition_url",
        return_value="/media/avatar.webp",
    )
    post_queryset = Post.objects.live().descendant_of(episode.podcast).order_by("-visible_date")

    queryset_data = PostQuerySnapshot.create_from_post_queryset(
        request=rf.get("/"),
        site=episode.podcast.get_site(),
        queryset=post_queryset,
    )
    assignments = [
        queryset_data.post_by_id[episode.pk].visible_contributor_assignments[0],
        queryset_data.post_by_id[other_episode.pk].visible_contributor_assignments[0],
    ]

    assert compute_avatar_rendition_url.call_count == 1
    assert assignments[0].contributor is assignments[1].contributor
    assert [assignment.get_avatar_rendition_url() for assignment in assignments] == [
        "/media/avatar.webp",
        "/media/avatar.webp",
    ]


@pytest.mark.django_db
def test_feed_repository_last_build_date_uses_newest_visible_date(rf, episode):
    older_date = timezone.now() - timezone.timedelta(days=2)
    newer_date = timezone.now()
    episode.visible_date = older_date
    episode.save()
    newer_episode = EpisodeFactory(
        owner=episode.owner,
        parent=episode.podcast,
        title="newer podcast episode",
        slug="newer-podcast-entry",
        visible_date=newer_date,
        podcast_audio=episode.podcast_audio,
        body=episode.body,
    )
    post_queryset = Episode.objects.live().descendant_of(episode.podcast).order_by("visible_date")

    repository = FeedContext.create_from_django_models(
        request=rf.get("/"),
        blog=episode.podcast,
        post_queryset=post_queryset,
        template_base_dir="bootstrap4",
    )
    data = data_for_blog_cachable(
        request=rf.get("/"),
        blog=episode.podcast,
        is_paginated=False,
        post_queryset=post_queryset,
    )

    assert repository.blog.last_build_date == newer_episode.visible_date
    assert data["last_build_date"] == newer_episode.visible_date


# Small tests for repository coverage
