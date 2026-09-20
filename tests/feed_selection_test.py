"""Selection and repository boundaries without enabling public paged endpoints."""

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

import pytest
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.http import Http404
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from wagtail.models import PageViewRestriction, Site

from cast import appsettings
from cast.feed_selection import (
    CURSOR_SALT,
    FeedScope,
    InvalidFeedCursor,
    RestartFeedCursor,
    build_feed_page_context,
    decode_cursor,
    select_feed_page,
)
from cast.feeds import LatestEntriesFeed, RepositoryMixin, RssPodcastFeed
from cast.models import Post
from cast.models.repository import PostQuerySnapshot
from tests.factories import BlogFactory, EpisodeFactory, PostFactory

DATE = datetime(2025, 1, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)


def make_posts(blog, count):
    return [
        PostFactory(parent=blog, owner=blog.owner, title=f"post {i}", slug=f"post-{i}", body=[], visible_date=DATE)
        for i in range(count)
    ]


def payload(scope):
    return {"v": 1, "order": 1, "scope": asdict(scope), "date": DATE.isoformat(timespec="microseconds"), "pk": 12}


def signed(data):
    return signing.Signer(salt=CURSOR_SALT).sign_object(data)


@pytest.mark.django_db
@pytest.mark.parametrize("count", [0, 1, 3, 4, 9])
def test_walk_equal_dates(blog, site, count):
    posts = make_posts(blog, count)
    scope = FeedScope(site.pk, blog.pk)
    first = select_feed_page(scope, page_size=3)
    assert first.ids == tuple(p.pk for p in posts[::-1][:3])
    assert bool(first.next_cursor) == (count > 3)
    ids = list(first.ids)
    current = first
    while current.next_cursor:
        current = select_feed_page(scope, page_size=2, cursor=current.next_cursor)
        ids.extend(current.ids)
    assert ids == [p.pk for p in reversed(posts)]


@pytest.mark.django_db
def test_selection_is_lightweight_bounded_and_uses_tuple_predicate(blog, site, mocker):
    make_posts(blog, 8)
    scope = FeedScope(site.pk, blog.pk)
    hydrate = mocker.spy(PostQuerySnapshot, "create_from_post_queryset")
    first = select_feed_page(scope, page_size=2)
    with CaptureQueriesContext(connection) as queries:
        page = select_feed_page(scope, page_size=2, cursor=first.next_cursor)
    sql = queries[-1]["sql"]
    assert "LIMIT 3" in sql and "OFFSET" not in sql and "COUNT(" not in sql
    assert '"body"' not in sql and '"visible_date"' in sql
    assert ") < (" in sql
    assert len(page.ids) == 2
    hydrate.assert_not_called()


@pytest.mark.django_db
def test_fallback_predicate_matches_tuple(blog, site, monkeypatch):
    posts = make_posts(blog, 5)
    Post.objects.filter(pk=posts[0].pk).update(visible_date=DATE - timedelta(days=1))
    scope = FeedScope(site.pk, blog.pk)
    first = select_feed_page(scope, page_size=2)
    expected = select_feed_page(scope, page_size=2, cursor=first.next_cursor)
    monkeypatch.setattr(connection, "vendor", "fallback")
    assert select_feed_page(scope, page_size=2, cursor=first.next_cursor) == expected


@pytest.mark.django_db
def test_changes_between_pages(blog, site):
    posts = make_posts(blog, 6)
    scope = FeedScope(site.pk, blog.pk)
    first = select_feed_page(scope, page_size=2)
    boundary = posts[-2]
    boundary.delete()
    PostFactory(parent=blog, owner=blog.owner, title="new", slug="new", body=[], visible_date=DATE + timedelta(days=1))
    second = select_feed_page(scope, page_size=3, cursor=first.next_cursor)
    assert second.ids == tuple(p.pk for p in posts[1:4][::-1])
    # Backdating a previously returned item can repeat it: no snapshot promise.
    Post.objects.filter(pk=posts[-1].pk).update(visible_date=DATE - timedelta(days=2))
    tail = select_feed_page(scope, cursor=second.next_cursor)
    assert tail.ids == (posts[0].pk, posts[-1].pk)


@pytest.mark.django_db
@pytest.mark.parametrize("change", ["restrict", "unpublish", "delete"])
def test_child_visibility_and_owner_isolation(blog, site, change):
    posts = make_posts(blog, 3)
    other = BlogFactory(parent=site.root_page, owner=blog.owner)
    make_posts(other, 2)
    hidden = posts[-1]
    removed_id = hidden.pk
    if change == "restrict":
        PageViewRestriction.objects.create(page=hidden, restriction_type=PageViewRestriction.LOGIN)
    elif change == "unpublish":
        hidden.unpublish()
    else:
        hidden.delete()
    page = select_feed_page(FeedScope(site.pk, blog.pk))
    assert removed_id not in page.ids
    assert page.ids == (posts[1].pk, posts[0].pk)


@pytest.mark.django_db
@pytest.mark.parametrize("inherited", [False, True])
def test_root_restrictions_precede_cursor_recovery(blog, site, inherited):
    PageViewRestriction.objects.create(
        page=site.root_page if inherited else blog, restriction_type=PageViewRestriction.LOGIN
    )
    with pytest.raises(Http404):
        select_feed_page(FeedScope(site.pk, blog.pk), cursor="invalid")


@pytest.mark.django_db
def test_wrong_site_missing_or_unpublished_root(blog, site):
    other = BlogFactory(parent=site.root_page, owner=blog.owner)
    wrong_site = Site.objects.create(hostname="other.example", root_page=other)
    for scope in [FeedScope(wrong_site.pk, blog.pk), FeedScope(999999, blog.pk), FeedScope(site.pk, 999999)]:
        with pytest.raises(Http404):
            select_feed_page(scope)
    blog.unpublish()
    with pytest.raises(Http404):
        select_feed_page(FeedScope(site.pk, blog.pk))


@pytest.mark.parametrize("size", [True, False, 0, -1, 501, 1.5, "2", None])
def test_invalid_size_without_database(size):
    with pytest.raises(ValueError, match="page size"):
        select_feed_page(FeedScope(1, 2), page_size=size)


@pytest.mark.parametrize(
    "changes",
    [
        {"site_id": True},
        {"blog_id": 0},
        {"blog_id": 2**63},
        {"kind": "unknown"},
        {"representation": "json"},
        {"audio_format": "mp3"},
        {"kind": "podcast"},
        {"family": "../bad"},
        {"family": 3},
    ],
)
def test_invalid_scope(changes):
    with pytest.raises(ValueError):
        replace(FeedScope(1, 2), **changes)


@pytest.mark.parametrize("value", ["", "x" * 1025, "💩", "a:b", None, ".abc:" + "a" * 43])
def test_malformed_envelope(value):
    with pytest.raises(InvalidFeedCursor):
        decode_cursor(value, FeedScope(1, 2))


@pytest.mark.parametrize(
    "changes,exception",
    [
        ({"v": True}, InvalidFeedCursor),
        ({"v": 2}, RestartFeedCursor),
        ({"extra": "field"}, InvalidFeedCursor),
        ({"scope": None}, InvalidFeedCursor),
        ({"scope": {}}, InvalidFeedCursor),
        ({"order": "1"}, InvalidFeedCursor),
        ({"order": 2}, RestartFeedCursor),
        ({"pk": True}, InvalidFeedCursor),
        ({"pk": 0}, InvalidFeedCursor),
        ({"date": 1}, InvalidFeedCursor),
        ({"date": "bad"}, InvalidFeedCursor),
        ({"date": "2025-01-01T12:00:00.123456"}, InvalidFeedCursor),
        ({"date": "2025-01-01T12:00:00+00:00"}, InvalidFeedCursor),
        ({"date": "2025-01-01T12:00:00.123456+01:00"}, InvalidFeedCursor),
    ],
)
def test_signed_invalid_payload(changes, exception):
    scope = FeedScope(1, 2)
    data = payload(scope) | changes
    with pytest.raises(exception):
        decode_cursor(signed(data), scope)


@pytest.mark.parametrize("data", [[], {"v": 1}])
def test_bad_payload_shape(data):
    with pytest.raises(InvalidFeedCursor):
        decode_cursor(signed(data), FeedScope(1, 2))


def test_signed_non_json_and_invalid_base64():
    signer = signing.Signer(salt=CURSOR_SALT)
    for value in ["a", signing.b64_encode(b"not json").decode()]:
        with pytest.raises(InvalidFeedCursor):
            decode_cursor(signer.sign(value), FeedScope(1, 2))


@pytest.mark.parametrize(
    "changes",
    [
        {"site_id": 3},
        {"blog_id": 3},
        {"kind": "podcast", "audio_format": "m4a"},
        {"representation": "atom"},
        {"family": "legacy"},
    ],
)
def test_foreign_scope(changes):
    scope = FeedScope(1, 2)
    with pytest.raises(InvalidFeedCursor, match="another scope"):
        decode_cursor(signed(payload(replace(scope, **changes))), scope)


def test_audio_scope_and_rotation():
    scope = FeedScope(1, 2, kind="podcast", audio_format="m4a")
    with pytest.raises(InvalidFeedCursor):
        decode_cursor(signed(payload(scope)), replace(scope, audio_format="mp3"))
    with override_settings(SECRET_KEY="old-test-key", SECRET_KEY_FALLBACKS=[]):
        cursor = signed(payload(scope))
    with override_settings(SECRET_KEY="new-test-key", SECRET_KEY_FALLBACKS=["old-test-key"]):
        assert decode_cursor(cursor, scope) == (DATE, 12)
    with override_settings(SECRET_KEY="new-test-key", SECRET_KEY_FALLBACKS=[]):
        with pytest.raises(RestartFeedCursor):
            decode_cursor(cursor, scope)


@pytest.mark.django_db
@pytest.mark.parametrize("repository", ["default", "django"])
@pytest.mark.parametrize("is_podcast", [False, True])
@pytest.mark.parametrize("count", [0, 1, 4])
def test_bounded_repository_and_rendering(blog, episode, site, rf, mocker, monkeypatch, repository, is_podcast, count):
    root = episode.blog if is_podcast else blog
    if is_podcast:
        episode.delete()
        for i in range(count):
            EpisodeFactory(
                parent=root,
                owner=root.owner,
                title=f"episode {i}",
                slug=f"episode-{i}",
                body=[],
                visible_date=DATE,
                podcast_audio=episode.podcast_audio,
            )
        EpisodeFactory(parent=root, owner=root.owner, title="no audio", slug="no-audio", body=[], visible_date=DATE)
    else:
        make_posts(root, count)
    scope = FeedScope(
        site.pk, root.pk, kind="podcast" if is_podcast else "blog", audio_format="m4a" if is_podcast else None
    )
    page = select_feed_page(scope, page_size=2)
    hydrate = mocker.spy(PostQuerySnapshot, "create_from_post_queryset")
    rendered = []
    original = RepositoryMixin.item_description

    def description(self, item):
        rendered.append(item.pk)
        return original(self, item)

    monkeypatch.setattr(RepositoryMixin, "item_description", description)
    request = rf.get("/feed/")
    monkeypatch.setattr(appsettings, "CAST_REPOSITORY", repository)
    context = build_feed_page_context(request, page)
    assert tuple(post.pk for post in context.post_queryset) == page.ids
    assert len(context.post_by_id) == min(2, count)
    if count == 0:
        with CaptureQueriesContext(connection) as metadata_queries:
            assert context.blog.last_build_date is not None
        assert len(metadata_queries) == 0
    assert tuple(hydrate.call_args.kwargs["queryset"].values_list("pk", flat=True)) == page.ids
    feed = RssPodcastFeed(repository=context) if is_podcast else LatestEntriesFeed(repository=context)
    kwargs = {"slug": root.slug}
    if is_podcast:
        kwargs["audio_format"] = "m4a"
    response = feed(request, **kwargs)
    assert response.status_code == 200
    assert tuple(rendered) == page.ids


@pytest.mark.django_db
def test_hydration_rechecks_visibility_without_refilling(blog, site, rf):
    posts = make_posts(blog, 3)
    page = select_feed_page(FeedScope(site.pk, blog.pk), page_size=2)
    posts[-1].unpublish()
    for mode in ["default", "django"]:
        context = build_feed_page_context(rf.get("/"), page, repository=mode)
        assert tuple(post.pk for post in context.post_queryset) == (posts[-2].pk,)
    with pytest.raises(ValueError, match="repository"):
        build_feed_page_context(rf.get("/"), page, repository="invalid")


@pytest.mark.django_db
def test_context_wrong_or_missing_site(blog, site, rf, mocker):
    page = select_feed_page(FeedScope(site.pk, blog.pk))
    for result in [None, Site(pk=999)]:
        mocker.patch.object(Site, "find_for_request", return_value=result)
        with pytest.raises(Http404):
            build_feed_page_context(rf.get("/"), page)


@override_settings(USE_TZ=False)
def test_naive_datetime_configuration_is_not_silently_reinterpreted():
    with pytest.raises(ImproperlyConfigured, match="USE_TZ"):
        select_feed_page(FeedScope(1, 2))


def test_wrong_identity_precedes_retired_order_and_missing_fields_are_invalid():
    scope = FeedScope(1, 2)
    data = payload(replace(scope, blog_id=3)) | {"order": 99}
    with pytest.raises(InvalidFeedCursor):
        decode_cursor(signed(data), scope)
    data = payload(scope)
    del data["scope"]["family"]
    with pytest.raises(InvalidFeedCursor):
        decode_cursor(signed(data), scope)


@pytest.mark.django_db
def test_timezone_and_maximum_page_size(blog, site):
    post = make_posts(blog, 1)[0]
    local_date = DATE.astimezone(timezone(timedelta(hours=5, minutes=30)))
    Post.objects.filter(pk=post.pk).update(visible_date=local_date)
    scope = FeedScope(site.pk, blog.pk)
    assert select_feed_page(scope, page_size=500).ids == (post.pk,)
    # Same instant as the boundary must use the pk tiebreak, not local clock time.
    assert select_feed_page(scope, cursor=signed(payload(scope) | {"pk": post.pk + 1})).ids == (post.pk,)
    assert select_feed_page(scope, cursor=signed(payload(scope) | {"pk": post.pk})).ids == ()


@pytest.mark.django_db
def test_inherited_child_restriction_and_move_out(blog, site):
    nested = BlogFactory(parent=blog, owner=blog.owner)
    hidden = make_posts(nested, 1)[0]
    visible = make_posts(blog, 1)[0]
    PageViewRestriction.objects.create(page=nested, restriction_type=PageViewRestriction.PASSWORD)
    scope = FeedScope(site.pk, blog.pk)
    assert select_feed_page(scope).ids == (visible.pk,)
    other = BlogFactory(parent=site.root_page, owner=blog.owner)
    visible.move(other, pos="last-child")
    assert select_feed_page(scope).ids == ()
    assert hidden.pk not in select_feed_page(scope).ids


@pytest.mark.django_db
def test_podcast_continuation_uses_post_index_columns(episode, site):
    Post.objects.filter(pk=episode.pk).update(visible_date=DATE)
    other = EpisodeFactory(
        parent=episode.blog,
        owner=episode.owner,
        title="next",
        slug="next",
        body=[],
        visible_date=DATE,
        podcast_audio=episode.podcast_audio,
    )
    scope = FeedScope(site.pk, episode.blog.pk, kind="podcast", audio_format="m4a")
    first = select_feed_page(scope, page_size=1)
    assert first.ids == (other.pk,)
    with CaptureQueriesContext(connection) as queries:
        second = select_feed_page(scope, page_size=1, cursor=first.next_cursor)
    assert second.ids == (episode.pk,)
    assert '("cast_post"."visible_date", "cast_post"."page_ptr_id") <' in queries[-1]["sql"]
