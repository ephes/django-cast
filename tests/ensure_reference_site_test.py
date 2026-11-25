import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from cast.models import Blog, Episode, Podcast, Post
from cast.views.styleguide import (
    STYLEGUIDE_BLOG_SLUG,
    STYLEGUIDE_EPISODE_SLUG,
    STYLEGUIDE_PODCAST_SLUG,
    STYLEGUIDE_POST_SLUG_PREFIX,
)

pytestmark = [pytest.mark.django_db, pytest.mark.slow]


def test_ensure_reference_site_creates_content(site):
    """Command creates blog, podcast, posts, and episode."""
    call_command("ensure_reference_site")
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()
    assert Podcast.objects.filter(slug=STYLEGUIDE_PODCAST_SLUG).exists()
    assert Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX).count() >= 6
    assert Episode.objects.filter(slug=STYLEGUIDE_EPISODE_SLUG).exists()


def test_ensure_reference_site_is_idempotent(site):
    """Running twice does not duplicate content."""
    call_command("ensure_reference_site")
    first_blog_count = Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).count()
    first_post_count = Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX).count()

    call_command("ensure_reference_site")
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).count() == first_blog_count
    assert Post.objects.filter(slug__startswith=STYLEGUIDE_POST_SLUG_PREFIX).count() == first_post_count


def test_ensure_reference_site_reset(site):
    """--reset deletes and recreates the reference site."""
    call_command("ensure_reference_site")
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()

    call_command("ensure_reference_site", reset=True)
    # After reset, content is recreated
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()


def test_ensure_reference_site_invalid_theme(site):
    """Invalid theme slug raises CommandError."""
    with pytest.raises(CommandError, match="not available"):
        call_command("ensure_reference_site", theme="nonexistent-theme")


def test_ensure_reference_site_with_theme(site):
    """--theme selects a specific theme."""
    call_command("ensure_reference_site", theme="plain")
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()


def test_ensure_reference_site_with_renditions(site):
    """--with-renditions flag does not crash."""
    call_command("ensure_reference_site", with_renditions=True)
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()


def test_ensure_reference_site_remote_media_flag(site, settings):
    """--remote-media enables the remote media setting."""
    # No configured URLs: the explicit flag stays local to this invocation.
    call_command("ensure_reference_site", remote_media=True)
    assert Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).exists()
    assert not hasattr(settings, "CAST_STYLEGUIDE_REMOTE_MEDIA")


def test_reset_preserves_unrelated_colliding_pages(site, blog, podcast, user):
    from wagtail.models import Page

    from tests.factories import BlogFactory, EpisodeFactory, PodcastFactory, PostFactory

    call_command("ensure_reference_site")
    unrelated_blog = BlogFactory(parent=blog, owner=user, slug=STYLEGUIDE_BLOG_SLUG)
    unrelated_podcast = PodcastFactory(parent=blog, owner=user, slug=STYLEGUIDE_PODCAST_SLUG)
    unrelated_post = PostFactory(
        parent=blog, title="Unrelated post", owner=user, slug=f"{STYLEGUIDE_POST_SLUG_PREFIX}-1"
    )
    unrelated_episode = EpisodeFactory(
        parent=podcast, title="Unrelated episode", owner=user, slug=STYLEGUIDE_EPISODE_SLUG
    )
    ids = [page.pk for page in (unrelated_blog, unrelated_podcast, unrelated_post, unrelated_episode)]
    reference = Blog.objects.child_of(site.root_page).get(slug=STYLEGUIDE_BLOG_SLUG)
    reference_id = reference.pk
    call_command("ensure_reference_site", reset=True)
    assert Page.objects.filter(pk__in=ids).count() == len(ids)
    assert not Page.objects.filter(pk=reference_id).exists()
    assert Blog.objects.child_of(site.root_page).get(slug=STYLEGUIDE_BLOG_SLUG).owner.username == "styleguide"


@pytest.mark.parametrize("collision", ["owner", "no_owner", "type", "duplicate"])
def test_reset_refuses_ambiguous_reference_roots(site, user, collision):
    from wagtail.models import Page

    from tests.factories import BlogFactory

    call_command("ensure_reference_site")
    reference = Blog.objects.child_of(site.root_page).get(slug=STYLEGUIDE_BLOG_SLUG)
    if collision in {"owner", "no_owner"}:
        reference.owner = user if collision == "owner" else None
        reference.save()
    elif collision == "type":
        reference.delete()
        site.root_page.refresh_from_db()
        site.root_page.add_child(instance=Page(title="Unrelated", slug=STYLEGUIDE_BLOG_SLUG))
    else:
        site.root_page.refresh_from_db()
        duplicate = BlogFactory(parent=site.root_page, owner=reference.owner, slug="other-reference")
        # Simulate ambiguous legacy data, bypassing Wagtail's sibling slug validation.
        Page.objects.filter(pk=duplicate.pk).update(slug=STYLEGUIDE_BLOG_SLUG)
    before = list(Page.objects.values())
    from cast.models import Audio, Video

    media_before = (Audio.objects.count(), Video.objects.count())
    with pytest.raises(CommandError, match="ownership"):
        call_command("ensure_reference_site", reset=True)
    assert list(Page.objects.values()) == before
    # The refusal happens before any media is prepared.
    assert (Audio.objects.count(), Video.objects.count()) == media_before


@pytest.mark.parametrize("failure", ["delete", "posts", "context", "media"])
def test_failed_reset_preserves_original_reference_tree(site, monkeypatch, failure):
    from wagtail.models import Page

    from cast.views import styleguide as styleguide_view

    call_command("ensure_reference_site")
    pages_before = list(Page.objects.values())
    posts_before = list(Post.objects.values())
    reference_id = Blog.objects.get(slug=STYLEGUIDE_BLOG_SLUG).pk

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic rebuild failure")

    if failure == "delete":
        original_delete = Page.delete

        def delete_then_fail(page, *args, **kwargs):
            result = original_delete(page, *args, **kwargs)
            assert not Page.objects.filter(pk=page.pk).exists()
            fail()
            return result

        monkeypatch.setattr(Page, "delete", delete_then_fail)
    elif failure == "posts":
        original_ensure_posts = styleguide_view._ensure_posts

        def create_then_fail(*args, **kwargs):
            original_ensure_posts(*args, **kwargs)
            assert not Page.objects.filter(pk=reference_id).exists()
            fail()

        monkeypatch.setattr(styleguide_view, "_ensure_posts", create_then_fail)
    elif failure == "context":
        monkeypatch.setattr("cast.management.commands.ensure_reference_site._styleguide_context", fail)
    else:

        def media_failure(*args, **kwargs):
            assert Page.objects.filter(pk=reference_id).exists()
            fail()

        monkeypatch.setattr(styleguide_view, "_create_styleguide_media", media_failure)
    with pytest.raises(RuntimeError, match="synthetic rebuild"):
        call_command("ensure_reference_site", reset=True)
    assert list(Page.objects.values()) == pages_before
    assert list(Post.objects.values()) == posts_before


@pytest.mark.parametrize("fail_build", [False, True])
def test_command_flags_are_local_to_each_call(site, settings, monkeypatch, fail_build):
    from cast.management.commands import ensure_reference_site as command
    from cast.views import styleguide as styleguide_view

    settings.CAST_STYLEGUIDE_REMOTE_MEDIA = False
    settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS = False
    seen = []
    original_context = command._styleguide_context

    def context(*args, **kwargs):
        assert settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS is False
        seen.append((settings.CAST_STYLEGUIDE_REMOTE_MEDIA, kwargs["ensure_renditions"]))
        if fail_build:
            raise RuntimeError("synthetic option failure")
        return original_context(*args, **kwargs)

    monkeypatch.setattr(command, "_styleguide_context", context)
    monkeypatch.setattr(
        styleguide_view,
        "_fetch_styleguide_remote_media",
        lambda user: styleguide_view._empty_styleguide_remote_media(),
    )
    if fail_build:
        with pytest.raises(RuntimeError, match="synthetic option"):
            call_command("ensure_reference_site", remote_media=True, with_renditions=True)
    else:
        call_command("ensure_reference_site", remote_media=True, with_renditions=True)
    assert settings.CAST_STYLEGUIDE_REMOTE_MEDIA is False
    assert settings.CAST_STYLEGUIDE_GENERATE_RENDITIONS is False
    fail_build = False
    call_command("ensure_reference_site")
    assert seen == [(True, True), (False, None)]


@pytest.mark.parametrize("with_site", [False, True])
def test_reset_without_existing_reference_roots(site, with_site):
    from wagtail.models import Site

    if not with_site:
        Site.objects.all().delete()
    call_command("ensure_reference_site", reset=True)
    selected_site = Site.objects.first()
    assert Blog.objects.child_of(selected_site.root_page).filter(slug=STYLEGUIDE_BLOG_SLUG).exists()
    assert Podcast.objects.child_of(selected_site.root_page).filter(slug=STYLEGUIDE_PODCAST_SLUG).exists()


def test_reference_builder_does_not_adopt_foreign_roots(site, blog, user):
    from tests.factories import BlogFactory, PodcastFactory

    foreign_blog = BlogFactory(parent=blog, owner=user, slug=STYLEGUIDE_BLOG_SLUG)
    foreign_podcast = PodcastFactory(parent=blog, owner=user, slug=STYLEGUIDE_PODCAST_SLUG)
    call_command("ensure_reference_site")
    reference_blog = Blog.objects.child_of(site.root_page).get(slug=STYLEGUIDE_BLOG_SLUG)
    reference_podcast = Podcast.objects.child_of(site.root_page).get(slug=STYLEGUIDE_PODCAST_SLUG)
    assert reference_blog.pk != foreign_blog.pk
    assert reference_podcast.pk != foreign_podcast.pk
    assert not Post.objects.descendant_of(foreign_blog).exists()
    assert not Episode.objects.descendant_of(foreign_podcast).exists()


@pytest.mark.parametrize("reset", [False, True])
def test_media_preparation_runs_outside_the_page_transaction(site, monkeypatch, reset):
    """Remote downloads must not hold page row locks or SQLite's write lock."""
    from django.db import connection

    from cast.views import styleguide as styleguide_view

    call_command("ensure_reference_site")
    test_depth = len(connection.atomic_blocks)
    depths = []

    def fetch(user):
        depths.append(len(connection.atomic_blocks))
        return styleguide_view._empty_styleguide_remote_media()

    monkeypatch.setattr(styleguide_view, "_fetch_styleguide_remote_media", fetch)
    call_command("ensure_reference_site", reset=reset)
    assert depths == [test_depth]
