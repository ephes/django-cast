# ruff: noqa: F401,F811,I001
import json
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.files.base import ContentFile
from django.test import RequestFactory

from cast.devdata import create_audio, create_blog, create_gallery, create_image, create_podcast, create_user
from cast.models import Audio, Post
from cast.views import styleguide as styleguide_view
from cast.views.styleguide import StyleguideRemoteFile, StyleguideRemoteVideo


class DummyResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _find_block_types(value, target_type: str) -> bool:
    if isinstance(value, dict):
        if value.get("type") == target_type:
            return True
        return any(_find_block_types(child, target_type) for child in value.values())
    if isinstance(value, list):
        return any(_find_block_types(child, target_type) for child in value)
    return False


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00"
        b"\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc````"
        b"\x00\x00\x00\x05\x00\x01\xa5\xf6E@\x00\x00"
        b"\x00\x00IEND\xaeB`\x82"
    )


def test_styleguide_ensure_seed_data_orchestrates_seed_flow(monkeypatch):
    site = object()
    raw_user = object()
    user = object()
    blog = object()
    podcast = object()
    episode = object()
    post = object()
    cover_image = object()
    media_image = object()
    audio = object()
    galleries = [object()]
    transcript = {"version": 1, "transcripts": ["segment"]}
    remote_media = SimpleNamespace(
        gallery_images=["remote-image"],
        gallery_blocks=["<gallery/>"],
        cover_image=cover_image,
        audio=audio,
        transcript_data={"version": 1},
        video_url="https://example.com/video.mp4",
        video_poster_url="https://example.com/poster.jpg",
    )
    media = SimpleNamespace(audio=audio, image=media_image)
    calls: dict[str, object] = {}

    monkeypatch.setattr(styleguide_view, "_ensure_site", lambda: site)
    monkeypatch.setattr(styleguide_view.transaction, "atomic", nullcontext)
    monkeypatch.setattr(styleguide_view, "create_user", lambda **_kwargs: raw_user)
    monkeypatch.setattr(styleguide_view, "_harden_styleguide_user", lambda _user: user)
    monkeypatch.setattr(styleguide_view, "_ensure_blog", lambda _site, _user: blog)
    monkeypatch.setattr(styleguide_view, "_fetch_styleguide_remote_media", lambda _user: remote_media)
    monkeypatch.setattr(
        styleguide_view, "_create_styleguide_galleries", lambda images, _user: galleries if images else []
    )

    def fake_create_media(**kwargs):
        calls["create_media"] = kwargs
        return media

    monkeypatch.setattr(styleguide_view, "_create_styleguide_media", fake_create_media)
    monkeypatch.setattr(styleguide_view, "_ensure_posts", lambda *_args, **_kwargs: [post])
    monkeypatch.setattr(
        styleguide_view, "_ensure_styleguide_tags_and_categories", lambda posts: calls.setdefault("tags", posts)
    )
    monkeypatch.setattr(styleguide_view, "_ensure_podcast", lambda _site, _user: podcast)
    monkeypatch.setattr(
        styleguide_view,
        "_ensure_episode",
        lambda *_args, **_kwargs: (episode, transcript),
    )
    monkeypatch.setattr(
        styleguide_view,
        "_ensure_podlove_transcript",
        lambda _audio, _transcript: calls.setdefault("podlove", (_audio, _transcript)),
    )
    monkeypatch.setattr(
        styleguide_view,
        "_ensure_styleguide_comments",
        lambda current_post, *, site, user: calls.setdefault("comments", []).append((current_post, site, user)),
    )
    monkeypatch.setattr(
        styleguide_view,
        "_apply_styleguide_cover_images",
        lambda **kwargs: calls.setdefault("cover_images", kwargs),
    )

    seed = styleguide_view._ensure_styleguide_seed_data()
    assert seed == styleguide_view.StyleguideSeedData(
        blog=blog,
        media=media,
        galleries=galleries,
        gallery_blocks=["<gallery/>"],
        posts=[post],
        podcast=podcast,
        episode=episode,
        transcript=transcript,
        video_url="https://example.com/video.mp4",
        video_poster_url="https://example.com/poster.jpg",
    )
    assert calls["create_media"] == {
        "audio": audio,
        "gallery": galleries[0],
        "gallery_images": ["remote-image"],
        "user": user,
    }
    assert calls["tags"] == [post]
    assert calls["podlove"] == (audio, transcript)
    assert calls["comments"] == [(post, site, user)]
    assert calls["cover_images"] == {
        "blog": blog,
        "podcast": podcast,
        "posts": [post],
        "episode": episode,
        "image": cover_image,
    }


def test_styleguide_build_data_uses_seed_data_for_repositories(monkeypatch):
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")
    seed = styleguide_view.StyleguideSeedData(
        blog=object(),
        media=object(),
        galleries=[object()],
        gallery_blocks=["<gallery/>"],
        posts=[object()],
        podcast=object(),
        episode=object(),
        transcript={"version": 1},
        video_url="https://example.com/video.mp4",
        video_poster_url="https://example.com/poster.jpg",
    )
    blog_repository = object()
    podcast_repository = object()
    calls: list[tuple[object, object]] = []

    monkeypatch.setattr(styleguide_view, "_ensure_styleguide_seed_data", lambda: seed)

    def fake_create(current_request, current_page):
        calls.append((current_request, current_page))
        if current_page is seed.blog:
            return blog_repository
        return podcast_repository

    monkeypatch.setattr(
        styleguide_view.BlogIndexContext,
        "create_from_django_models",
        staticmethod(fake_create),
    )

    data = styleguide_view._build_styleguide_data(request)
    assert data.blog is seed.blog
    assert data.blog_repository is blog_repository
    assert data.media is seed.media
    assert data.galleries == seed.galleries
    assert data.gallery_blocks == seed.gallery_blocks
    assert data.posts == seed.posts
    assert data.podcast is seed.podcast
    assert data.episode is seed.episode
    assert data.podcast_repository is podcast_repository
    assert data.transcript == seed.transcript
    assert data.video_url == seed.video_url
    assert data.video_poster_url == seed.video_poster_url
    assert calls == [(request, seed.blog), (request, seed.podcast)]


@pytest.mark.django_db
def test_styleguide_build_data_without_posts(monkeypatch):
    factory = RequestFactory()
    request = factory.get("/cast/styleguide/")

    monkeypatch.setattr(styleguide_view, "_ensure_posts", lambda *_args, **_kwargs: [])
    data = styleguide_view._build_styleguide_data(request)
    assert data.posts == []


@pytest.mark.django_db
def test_styleguide_ensure_episode_branches(settings, site, monkeypatch):
    settings.CAST_STYLEGUIDE_TRANSCRIPT_MAX_SEGMENTS = 2
    user = create_user(name="episode-user", password="episode-user")
    create_blog(owner=user, site=site)
    podcast = create_podcast(owner=user, site=site)
    media = styleguide_view._create_styleguide_media(gallery=None, gallery_images=[], audio=None, user=user)

    galleries = [create_gallery(images=[create_image()])]
    episode, transcript = styleguide_view._ensure_episode(
        podcast,
        user,
        media,
        galleries,
        None,
        include_video_in_body=False,
    )
    assert episode.podcast_audio is not None
    assert transcript["transcripts"]

    episode.body = json.dumps(
        styleguide_view._build_styleguide_body(
            media=media,
            include_media=True,
            galleries=galleries,
            include_video=False,
        )
    )
    episode.podcast_audio = None
    episode.save()

    monkeypatch.setattr(styleguide_view, "_styleguide_should_refresh_body", lambda *_args, **_kwargs: True)

    episode_again, transcript_again = styleguide_view._ensure_episode(
        podcast,
        user,
        media,
        galleries,
        transcript,
        include_video_in_body=False,
    )
    assert episode_again.pk == episode.pk
    assert transcript_again["transcripts"]


@pytest.mark.django_db
def test_styleguide_ensure_episode_does_not_refresh_body(settings, site, monkeypatch):
    user = create_user(name="episode-no-refresh", password="episode-no-refresh")
    create_blog(owner=user, site=site)
    podcast = create_podcast(owner=user, site=site)
    media = styleguide_view._create_styleguide_media(gallery=None, gallery_images=[], audio=None, user=user)
    galleries = [create_gallery(images=[create_image()])]

    episode, transcript = styleguide_view._ensure_episode(
        podcast,
        user,
        media,
        galleries,
        None,
        include_video_in_body=False,
    )
    episode.body = "[]"
    episode.save()

    monkeypatch.setattr(styleguide_view, "_styleguide_should_refresh_body", lambda *_args, **_kwargs: False)
    episode_again, _transcript_again = styleguide_view._ensure_episode(
        podcast,
        user,
        media,
        galleries,
        transcript,
        include_video_in_body=False,
    )
    assert episode_again.pk == episode.pk


@pytest.mark.django_db
def test_styleguide_comments_parent_id_branch(monkeypatch, site, comments_enabled):
    user = create_user(name="comment-user", password="comment-user")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    class FakeField:
        def __init__(self, name):
            self.name = name

    class FakeManager:
        def __init__(self):
            self.created = []

        def filter(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return []

        def create(self, **kwargs):
            self.created.append(SimpleNamespace(**kwargs))
            return self.created[-1]

    class FakeCommentModel:
        _meta = SimpleNamespace(fields=[FakeField("parent_id"), FakeField("comment")])
        objects = FakeManager()

    import django_comments

    monkeypatch.setattr(django_comments, "get_model", lambda: FakeCommentModel)

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    assert FakeCommentModel.objects.created


@pytest.mark.django_db
def test_styleguide_comments_update_flags(settings, site, comments_enabled):
    settings.CAST_ENABLE_STYLEGUIDE = True
    user = create_user(name="comment-update", password="comment-update")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-update", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    from django.contrib.contenttypes.models import ContentType
    from django.contrib.sites.models import Site as DjangoSite
    from django_comments import get_model as get_comment_model

    comment_model = get_comment_model()
    django_site, _created = DjangoSite.objects.get_or_create(
        id=settings.SITE_ID,
        defaults={"domain": "localhost", "name": "localhost"},
    )
    content_type = ContentType.objects.get_for_model(post)
    parent = comment_model.objects.create(
        content_type=content_type,
        object_pk=str(post.pk),
        site=django_site,
        user=user,
        user_name=user.username,
        user_email=f"{user.username}@example.com",
        comment="Old comment",
        submit_date=styleguide_view.timezone.now(),
        is_public=False,
        is_removed=True,
    )
    reply = comment_model.objects.create(
        content_type=content_type,
        object_pk=str(post.pk),
        site=django_site,
        user=user,
        user_name=user.username,
        user_email=f"{user.username}@example.com",
        comment="Old reply",
        submit_date=styleguide_view.timezone.now(),
        is_public=False,
        is_removed=True,
        parent=parent,
    )

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    parent.refresh_from_db()
    reply.refresh_from_db()
    assert parent.is_public is True
    assert parent.is_removed is False
    assert reply.is_public is True
    assert reply.is_removed is False


@pytest.mark.django_db
def test_styleguide_comments_without_reply(settings, site, comments_enabled):
    user = create_user(name="comment-orphan", password="comment-orphan")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-orphan", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    from django.contrib.contenttypes.models import ContentType
    from django.contrib.sites.models import Site as DjangoSite
    from django_comments import get_model as get_comment_model

    comment_model = get_comment_model()
    django_site, _created = DjangoSite.objects.get_or_create(
        id=settings.SITE_ID,
        defaults={"domain": "localhost", "name": "localhost"},
    )
    content_type = ContentType.objects.get_for_model(post)
    parent = comment_model.objects.create(
        content_type=content_type,
        object_pk=str(post.pk),
        site=django_site,
        user=user,
        user_name=user.username,
        user_email=f"{user.username}@example.com",
        comment="Parent",
        submit_date=styleguide_view.timezone.now(),
    )
    orphan = comment_model.objects.create(
        content_type=content_type,
        object_pk=str(post.pk),
        site=django_site,
        user=user,
        user_name=user.username,
        user_email=f"{user.username}@example.com",
        comment="Orphan",
        submit_date=styleguide_view.timezone.now(),
    )

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    parent.refresh_from_db()
    orphan.refresh_from_db()
    assert orphan.comment == "Orphan"


@pytest.mark.django_db
def test_styleguide_comments_without_parent_field(monkeypatch, site, comments_enabled):
    user = create_user(name="comment-noparent", password="comment-noparent")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-noparent", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    class FakeField:
        def __init__(self, name):
            self.name = name

    class FakeManager:
        def __init__(self, comments):
            self._comments = comments

        def filter(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return self._comments

    class FakeComment:
        def __init__(self, comment):
            self.comment = comment
            self.is_public = True
            self.is_removed = False
            self.saved = False

        def save(self, update_fields=None):
            self.saved = True
            return None

    parent_comment = FakeComment("Parent")
    reply_comment = FakeComment("Reply")

    class FakeCommentModel:
        _meta = SimpleNamespace(fields=[FakeField("comment")])
        objects = FakeManager([parent_comment, reply_comment])

    import django_comments

    monkeypatch.setattr(django_comments, "get_model", lambda: FakeCommentModel)

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    assert reply_comment.saved is True


@pytest.mark.django_db
def test_styleguide_comments_without_parent_field_single_comment(monkeypatch, site, comments_enabled):
    user = create_user(name="comment-single", password="comment-single")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-single", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    class FakeField:
        def __init__(self, name):
            self.name = name

    class FakeManager:
        def __init__(self, comments):
            self._comments = comments

        def filter(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return self._comments

    class FakeComment:
        def __init__(self, comment):
            self.comment = comment
            self.is_public = True
            self.is_removed = False
            self.saved = False

        def save(self, update_fields=None):
            self.saved = True
            return None

    parent_comment = FakeComment("Parent")

    class FakeCommentModel:
        _meta = SimpleNamespace(fields=[FakeField("comment")])
        objects = FakeManager([parent_comment])

    import django_comments

    monkeypatch.setattr(django_comments, "get_model", lambda: FakeCommentModel)

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    assert parent_comment.saved is True


@pytest.mark.django_db
def test_styleguide_comments_creates_parent_without_reply(monkeypatch, site, comments_enabled):
    user = create_user(name="comment-no-reply", password="comment-no-reply")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-no-reply", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    class FakeField:
        def __init__(self, name):
            self.name = name

    class FakeManager:
        def __init__(self):
            self.created = []

        def filter(self, **_kwargs):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return []

        def create(self, **kwargs):
            self.created.append(SimpleNamespace(**kwargs))
            return self.created[-1]

    class FakeCommentModel:
        _meta = SimpleNamespace(fields=[FakeField("comment")])
        objects = FakeManager()

    import django_comments

    monkeypatch.setattr(django_comments, "get_model", lambda: FakeCommentModel)

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)
    assert FakeCommentModel.objects.created


@pytest.mark.django_db
def test_styleguide_comments_creates_parent_and_reply(site, comments_enabled):
    user = create_user(name="comment-new", password="comment-new")
    blog = create_blog(owner=user, site=site)
    post = Post(title="Post", slug="post-new", owner=user)
    blog.add_child(instance=post)
    post = post.specific

    styleguide_view._ensure_styleguide_comments(post, site=site, user=user)

    from django_comments import get_model as get_comment_model

    comment_model = get_comment_model()
    comments = comment_model.objects.for_model(post).filter(user=user).order_by("submit_date", "pk").all()
    assert len(comments) >= 1


@pytest.mark.django_db
def test_ensure_posts_updates_stale_visible_date(site):
    """When an existing styleguide post has a visible_date in the wrong month, _ensure_posts updates it."""
    from dateutil.relativedelta import relativedelta

    from django.utils import timezone

    user = create_user(name="date-user", password="date-user")
    blog = create_blog(owner=user, site=site)

    # First call creates posts with spread dates
    galleries = [create_gallery(images=[create_image()])]
    media = styleguide_view._create_styleguide_media(gallery=None, gallery_images=[], audio=None, user=user)
    posts = styleguide_view._ensure_posts(blog, user, media, galleries, include_video_in_body=False)
    assert len(posts) >= 2

    # Set the second post's visible_date to "now" so it no longer matches the expected spread month
    second_post = Post.objects.get(pk=posts[1].pk)
    second_post.visible_date = timezone.now()
    second_post.save()

    # Second call should detect the stale date and update it
    posts_again = styleguide_view._ensure_posts(blog, user, media, galleries, include_video_in_body=False)
    refreshed = Post.objects.get(pk=posts_again[1].pk)
    now = timezone.now()
    expected_date = now - relativedelta(months=1)
    assert refreshed.visible_date.strftime("%Y-%m") == expected_date.strftime("%Y-%m")
