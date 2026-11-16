"""Repository projections must not mix independent sites with colliding IDs."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connections, models
from wagtail.models import Collection, Locale, Page, Site

from cast.models import Audio, Contributor, Episode, EpisodeContributor, Podcast, Post, Season, Transcript
from cast.models.repository import FeedContext, PostQuerySnapshot


@pytest.fixture
def independent_podcasts(settings):
    class BuildRouter:
        alias = "default"

        def db_for_read(self, model, **hints):
            return self.alias

        db_for_write = db_for_read

    build_router = BuildRouter()
    settings.DATABASE_ROUTERS = [build_router]
    result = {}
    for alias in ("default", "migration_other"):
        build_router.alias = alias
        ContentType.objects.clear_cache()
        locale, _ = Locale.objects.get_or_create(language_code="en")
        owner = get_user_model().objects.create(pk=90001, username=f"{alias}-owner")
        collection = Collection.objects.create(pk=90001, name=alias, path="9999", depth=1, numchild=0)
        root = Page(
            pk=90001,
            title=alias,
            slug="synthetic-root",
            path="9999",
            depth=1,
            locale=locale,
            content_type=ContentType.objects.get_for_model(Page),
        )
        models.Model.save(root, using=alias)
        podcast = root.add_child(
            instance=Podcast(
                title=alias,
                template_base_dir="plain",
                slug="synthetic",
                owner=owner,
                locale=locale,
                content_type=ContentType.objects.get_for_model(Podcast),
            )
        )
        audio = Audio.objects.create(pk=90001, title=alias, collection=collection, user=owner)
        season = Season.objects.create(pk=90001, podcast=podcast, number=1, name=alias)
        episode = podcast.add_child(
            instance=Episode(
                title=alias,
                slug="episode",
                owner=owner,
                locale=locale,
                podcast_audio=audio,
                season=season,
                content_type=ContentType.objects.get_for_model(Episode),
            )
        )
        contributor = Contributor.objects.create(pk=90001, display_name=alias, slug="synthetic")
        EpisodeContributor.objects.create(pk=90001, episode=episode, contributor=contributor, role="host")
        transcript = Transcript.objects.create(pk=90001, audio=audio, collection=collection)
        result[alias] = (podcast, episode, transcript)
    settings.DATABASE_ROUTERS = []
    ContentType.objects.clear_cache()
    yield result
    ContentType.objects.clear_cache()


def refuse_default(execute, sql, params, many, context):
    raise AssertionError(f"Repository touched default: {sql}")


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("model", [Post, Episode])
def test_snapshot_auxiliary_queries_follow_source(independent_podcasts, rf, monkeypatch, model):
    podcast, episode, transcript = independent_podcasts["migration_other"]
    # Wagtail's global URL registry is outside the repository data projection.
    monkeypatch.setattr(Post, "get_url", lambda *a, **kw: "/synthetic/episode/")
    monkeypatch.setattr(Post, "full_url", property(lambda self: "http://testserver/synthetic/episode/"))
    with connections["default"].execute_wrapper(refuse_default):
        snapshot = PostQuerySnapshot.create_from_post_queryset(
            request=rf.get("/"), site=None, queryset=model.objects.using("migration_other").filter(pk=episode.pk)
        )
        selected = snapshot.post_by_id[episode.pk]
        assert selected.title == "migration_other"
        assert selected.season.name == "migration_other"
        assert selected.visible_contributor_assignments[0].contributor.display_name == "migration_other"
        assert snapshot.transcript_by_audio_id[transcript.audio_id].pk == transcript.pk
        assert snapshot.podcast_audio_by_episode_id[episode.pk]._state.db == "migration_other"


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("is_podcast", [False, True])
def test_feed_selection_follows_blog_database(independent_podcasts, rf, monkeypatch, is_podcast):
    import cast.models.repository.contexts as contexts

    podcast, episode, _ = independent_podcasts["migration_other"]

    def capture(**kwargs):
        queryset = kwargs["post_queryset"]
        assert queryset.db == "migration_other"
        assert list(queryset.values_list("title", flat=True)) == ["migration_other"]
        return {}

    monkeypatch.setattr(contexts, "data_for_blog_cachable", capture)
    monkeypatch.setattr(Podcast, "get_url", lambda *a, **kw: "/synthetic/")
    with connections["default"].execute_wrapper(refuse_default):
        FeedContext.data_for_feed_cachable(request=rf.get("/"), blog=podcast, is_podcast=is_podcast)


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_cached_episode_preserves_nested_database_affinity(independent_podcasts):
    import json

    from cast.models.repository.serialization import deserialize_episode, serialize_episode

    _, episode, _ = independent_podcasts["migration_other"]
    restored = deserialize_episode(json.loads(json.dumps(serialize_episode(episode), default=str)))
    with connections["default"].execute_wrapper(refuse_default):
        assert restored._state.db == "migration_other"
        assert not restored._state.adding
        assert restored.podcast_audio.collection.name == "migration_other"
        assert restored.season.podcast.title == "migration_other"
        assignment = restored.visible_contributor_assignments[0]
        assert assignment._state.db == assignment.contributor._state.db == "migration_other"


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("kind", ["audio", "transcript", "image", "video", "blog", "post", "rendition"])
def test_cached_models_preserve_database_affinity(independent_podcasts, kind):
    import json

    from wagtail.images.models import Image, Rendition

    from cast.models import Video
    from cast.models.repository import serialization as ser

    podcast, episode, transcript = independent_podcasts["migration_other"]
    if kind == "rendition":
        image = Image.objects.using("migration_other").create(
            title="migration_other", file="synthetic.png", width=2, height=2, collection_id=90001
        )
        instance = Rendition.objects.using("migration_other").create(
            image=image, file="synthetic-small.png", width=1, height=1, filter_spec="width-1"
        )
        # Image is a genuine deferred relation after reconstruction.
        restored = ser.deserialize_renditions({1: [json.loads(json.dumps(ser.rendition_to_dict(instance)))]})[1][0]
        with connections["default"].execute_wrapper(refuse_default):
            assert restored.image.title == "migration_other"
        return
    if kind in {"image", "video"}:
        model = Image if kind == "image" else Video
        fields = {"file": "synthetic.png", "width": 2, "height": 2} if kind == "image" else {"user_id": 90001}
        instance = model.objects.using("migration_other").create(
            title="migration_other", collection_id=90001, **fields
        )
    else:
        instance = {"audio": episode.podcast_audio, "transcript": transcript, "blog": podcast, "post": episode}[kind]
    restored = getattr(ser, f"deserialize_{kind}")(
        json.loads(json.dumps(getattr(ser, f"serialize_{kind}")(instance), default=str))
    )
    with connections["default"].execute_wrapper(refuse_default):
        assert restored._state.db == "migration_other"
        assert not restored._state.adding
        if kind in {"audio", "transcript", "image", "video"}:
            assert restored.collection.name == "migration_other"
        if kind == "transcript":
            assert restored.audio.title == "migration_other"


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_feed_cache_roundtrip_keeps_source_site_and_relations(independent_podcasts, rf, monkeypatch):
    import json

    podcast, episode, _ = independent_podcasts["migration_other"]
    site = Site.objects.using("migration_other").create(hostname="synthetic.invalid", root_page_id=90001)
    request = rf.get("/")
    request._wagtail_site = site
    monkeypatch.setattr(Post, "get_url", lambda *a, **kw: "/synthetic/episode/")
    monkeypatch.setattr(Post, "full_url", property(lambda self: "http://testserver/synthetic/episode/"))
    monkeypatch.setattr(Podcast, "get_url", lambda *a, **kw: "/synthetic/")
    monkeypatch.setattr(Page, "get_url", lambda *a, **kw: "/synthetic/")
    with connections["default"].execute_wrapper(refuse_default):
        data = FeedContext.data_for_feed_cachable(request=request, blog=podcast, is_podcast=True)
        for payload in (data, json.loads(json.dumps(data, default=str))):
            feed = FeedContext.create_from_cachable_data(data=payload)
            restored = feed.post_by_id[episode.pk]
            assert restored.title == "migration_other"
            assert feed.site.root_page.title == "migration_other"
            assert feed.blog._state.db == "migration_other"
            assert feed.get_episode_feed_detail_repository(restored).podcast_audio.collection.name == "migration_other"
            assert restored.season.podcast.title == "migration_other"
            assert restored.visible_contributor_assignments[0].contributor.display_name == "migration_other"


def test_projection_refuses_unknown_database():
    from cast.models.repository.serialization import deserialize_audio

    with pytest.raises(ValueError, match="Unknown repository database"):
        deserialize_audio({"id": 1, "_database": "nonexistent"})


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_public_restrictions_follow_selected_database(independent_podcasts):
    from wagtail.models import PageViewRestriction

    from cast.blog_index import unfiltered_published_posts

    podcast, episode, _ = independent_podcasts["migration_other"]
    PageViewRestriction.objects.using("default").create(page_id=episode.pk, restriction_type="login")
    with connections["default"].execute_wrapper(refuse_default):
        assert list(unfiltered_published_posts(podcast).values_list("pk", flat=True)) == [episode.pk]
        models.Model.save(PageViewRestriction(page=episode, restriction_type="login"), using="migration_other")
        assert not unfiltered_published_posts(podcast).exists()


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_nested_contributor_avatar_link_and_artwork_keep_database(independent_podcasts):
    from wagtail.images.models import Image

    from cast.models import ContributorLink
    from cast.models.itunes import ItunesArtWork
    from cast.models.repository.serialization import (
        deserialize_blog,
        deserialize_episode_contributor,
        serialize_blog,
        serialize_episode_contributor,
    )

    podcast, episode, _ = independent_podcasts["migration_other"]
    assignment = EpisodeContributor.objects.using("migration_other").select_related("contributor").get(episode=episode)
    assignment.contributor.avatar = Image.objects.using("migration_other").create(
        title="Synthetic avatar", file="avatar.png", width=2, height=2, collection_id=90001
    )
    assignment.link = ContributorLink.objects.using("migration_other").create(
        contributor=assignment.contributor, service="website", url="https://synthetic.invalid/"
    )
    podcast.itunes_artwork = ItunesArtWork.objects.using("migration_other").create(
        original="artwork.png", original_width=2, original_height=2
    )
    restored = deserialize_episode_contributor(serialize_episode_contributor(assignment))
    rebuilt_blog = deserialize_blog(serialize_blog(podcast))
    with connections["default"].execute_wrapper(refuse_default):
        assert restored.contributor.avatar.collection.name == "migration_other"
        assert restored.link._state.db == restored.link.contributor._state.db == "migration_other"
        assert restored.episode.title == "migration_other"
        assert rebuilt_blog.itunes_artwork._state.db == "migration_other"


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("builder", ["snapshot", "feed"])
def test_repository_refuses_a_site_from_another_database(independent_podcasts, rf, builder):
    podcast, episode, _ = independent_podcasts["migration_other"]
    site = Site.objects.using("default").create(hostname="synthetic.invalid", root_page_id=90001)
    request = rf.get("/")
    request._wagtail_site = site
    with connections["default"].execute_wrapper(refuse_default):
        with pytest.raises(ValueError, match="source database"):
            if builder == "snapshot":
                PostQuerySnapshot.create_from_post_queryset(
                    request=request, site=site, queryset=Post.objects.using("migration_other").filter(pk=episode.pk)
                )
            else:
                FeedContext.data_for_feed_cachable(request=request, blog=podcast, is_podcast=True)
