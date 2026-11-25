"""Real editor writes on an independent, fully routed synthetic database."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from taggit.models import Tag
from wagtail.models import Locale, Page, Revision

from cast.api.editor.views import EpisodeEditorMixin, PostEditorMixin
from cast.models import Blog, Episode, Podcast, Post, Season
from tests.factories import EpisodeFactory, PodcastFactory, PostFactory


class EditorRouter:
    def db_for_read(self, model, **hints):
        return "migration_other"

    db_for_write = db_for_read


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("kind", ["post", "episode"])
@pytest.mark.parametrize("operation", ["create", "patch"])
def test_routed_editor_revision_failure_rolls_back(settings, api_client, monkeypatch, kind, operation):
    settings.DATABASE_ROUTERS = [EditorRouter()]
    ContentType.objects.clear_cache()
    alias = "migration_other"
    locale = Locale.objects.create(language_code="en")
    root = Page.add_root(instance=Page(title="Synthetic root", slug="root", locale=locale))
    parent_model = Blog if kind == "post" else Podcast
    parent = root.add_child(instance=parent_model(title="Synthetic parent", slug="parent", locale=locale))
    user = get_user_model().objects.create(username="routed-editor", is_staff=True, is_superuser=True)
    api_client.force_authenticate(user=user)
    payload = {
        "parent": {"id": parent.pk},
        "title": "Synthetic child",
        "slug": "routed-child",
        "tags": ["routed-tag"],
        "overview": [],
    }
    url = reverse(f"cast:api:editor_{kind}_create")
    if operation == "patch":
        created = api_client.post(url, payload, format="json")
        assert created.status_code == 201, created.content
        payload = {
            "base_revision_id": created.json()["latest_revision_id"],
            "title": "Changed",
            "slug": "changed-slug",
        }
        url = reverse(f"cast:api:editor_{kind}_detail", kwargs={"pk": created.json()["id"]})
    before = {
        name: list(model.objects.using(alias).values())
        for name, model in (("page", Page), ("revision", Revision), ("tag", Tag))
    }
    original = Post.save_revision

    def fail_after_revision(self, *args, **kwargs):
        assert connections[alias].in_atomic_block, "page write has no transaction on its database"
        result = original(self, *args, **kwargs)
        assert result._state.db == alias
        raise RuntimeError("Synthetic revision failure")

    monkeypatch.setattr(Post, "save_revision", fail_after_revision)
    with pytest.raises(RuntimeError, match="Synthetic revision failure"):
        getattr(api_client, "post" if operation == "create" else "patch")(url, payload, format="json")
    after = {
        name: list(model.objects.using(alias).values())
        for name, model in (("page", Page), ("revision", Revision), ("tag", Tag))
    }
    assert after == before
    assert not Page.objects.using("default").filter(slug__in=["routed-child", "changed-slug"]).exists()
    ContentType.objects.clear_cache()


@pytest.fixture
def replica_parent():
    def create(parent):
        with override_settings(DATABASE_ROUTERS=[EditorRouter()]):
            ContentType.objects.clear_cache()
            try:
                locale = Locale.objects.create(language_code="en")
                root = Page.add_root(instance=Page(title="Replica root", slug="replica-root", locale=locale))
                return root.add_child(
                    instance=type(parent)(pk=parent.pk, title="Replica parent", slug="replica-parent", locale=locale)
                )
            finally:
                ContentType.objects.clear_cache()

    return create


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("writer_owns_season", [True, False])
@pytest.mark.parametrize("operation", ["create", "patch"])
def test_episode_write_resolves_season_on_podcast_database(
    settings, api_client, admin_user, podcast, replica_parent, monkeypatch, writer_owns_season, operation
):
    other_podcast = PodcastFactory(parent=podcast.get_parent())
    season = Season.objects.create(podcast=podcast if writer_owns_season else other_podcast, number=1)
    replica_podcast = replica_parent(podcast)
    with override_settings(DATABASE_ROUTERS=[EditorRouter()]):
        try:
            other_replica_podcast = replica_podcast.get_parent().add_child(
                instance=Podcast(title="Other replica podcast", slug="other-replica-podcast")
            )
            Season.objects.create(
                pk=season.pk,
                podcast=other_replica_podcast if writer_owns_season else replica_podcast,
                number=1,
            )
        finally:
            ContentType.objects.clear_cache()

    class SeasonReadRouter:
        use_replica = False

        def db_for_read(self, model, **hints):
            if model is Season and self.use_replica:
                return "migration_other"

    routing = SeasonReadRouter()
    settings.DATABASE_ROUTERS = [routing]
    original_apply = EpisodeEditorMixin._apply_episode_metadata

    def apply_metadata(self, *args, **kwargs):
        # The page graph has already been admitted and its podcast locked.
        with monkeypatch.context() as context:
            context.setattr(routing, "use_replica", True)
            return original_apply(self, *args, **kwargs)

    api_client.force_authenticate(user=admin_user)
    payload = {"parent": {"id": podcast.pk}, "title": "Routed episode", "overview": []}
    if operation == "create":
        payload["season"] = {"id": season.pk}
        method, url, success_status = api_client.post, reverse("cast:api:editor_episode_create"), 201
    else:
        created = api_client.post(reverse("cast:api:editor_episode_create"), payload, format="json")
        assert created.status_code == 201, created.content
        episode_id = created.json()["id"]
        payload = {"base_revision_id": created.json()["latest_revision_id"], "season": {"id": season.pk}}
        method, url, success_status = (
            api_client.patch,
            reverse("cast:api:editor_episode_detail", kwargs={"pk": episode_id}),
            200,
        )
        revisions_before = Revision.objects.using("default").filter(object_id=str(episode_id)).count()
    monkeypatch.setattr(EpisodeEditorMixin, "_apply_episode_metadata", apply_metadata)
    response = method(url, payload, format="json")

    if writer_owns_season:
        assert response.status_code == success_status, response.content
        assert response.json()["season"] == {"id": season.pk}
        episode = Episode.objects.using("default").get(pk=response.json()["id"])
        if operation == "create":
            assert episode.season_id == season.pk
        else:
            assert episode.get_latest_revision().as_object().season_id == season.pk
    else:
        assert response.status_code == 400, response.content
        assert response.json()["errors"] == {
            "season": [{"code": "invalid", "message": "The selected season must belong to this episode's podcast."}]
        }
        if operation == "create":
            assert not Episode.objects.using("default").filter(slug="routed-episode").exists()
        else:
            assert Revision.objects.using("default").filter(object_id=str(episode_id)).count() == revisions_before


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("kind", ["post", "episode"])
def test_publish_response_reads_published_generation(
    settings, api_client, admin_user, blog, podcast, audio, replica_parent, monkeypatch, kind
):
    parent = blog if kind == "post" else podcast
    factory = PostFactory if kind == "post" else EpisodeFactory
    extra = {"podcast_audio": audio} if kind == "episode" else {}
    page = factory(parent=parent, title="Draft title", slug="draft-slug", owner=admin_user, live=False, **extra)
    page.title = "Published title"
    page.slug = "published-slug"
    revision = page.save_revision(user=admin_user)

    stale_parent = replica_parent(parent)
    with override_settings(DATABASE_ROUTERS=[EditorRouter()]):
        ContentType.objects.clear_cache()
        stale_parent.add_child(
            instance=type(page)(
                pk=page.pk, title="Stale title", slug="stale-slug", live=False, locale_id=stale_parent.locale_id
            )
        )
        ContentType.objects.clear_cache()

    class ReadRouter:
        published = False

        def db_for_read(self, model, **hints):
            if self.published and model in (Post, Episode):
                return "migration_other"
            return None

    read_router = ReadRouter()
    settings.DATABASE_ROUTERS = [read_router]
    original_publish = Revision.publish

    def publish(self, *args, **kwargs):
        result = original_publish(self, *args, **kwargs)
        read_router.published = True
        return result

    monkeypatch.setattr(Revision, "publish", publish)
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(reverse(f"cast:api:editor_{kind}_publish", args=[page.pk]), {}, format="json")

    assert response.status_code == 200, response.content
    data = response.json()
    assert data["status"] == "live"
    assert data["live"] is True
    assert data["title"] == "Published title"
    assert data["page_slug"] == "published-slug"
    assert data["public_url"].endswith("/published-slug/")
    assert data["latest_revision_id"] == data["published_revision_id"] == revision.pk


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("kind", ["post", "episode"])
def test_create_checks_siblings_under_locked_writer_parent(
    settings, api_client, admin_user, blog, podcast, replica_parent, monkeypatch, kind
):
    parent = blog if kind == "post" else podcast
    factory = PostFactory if kind == "post" else EpisodeFactory
    factory(parent=parent, title="Writer child", slug="reserved-slug", owner=admin_user)
    stale_parent = replica_parent(parent)
    with override_settings(DATABASE_ROUTERS=[EditorRouter()]):
        ContentType.objects.clear_cache()
        root = stale_parent.get_parent()
        ancestor = root.add_child(instance=Page(title="Previous location", slug="previous-location"))
        stale_parent.move(ancestor, pos="last-child")
        stale_parent.refresh_from_db()
        ContentType.objects.clear_cache()
    assert stale_parent.path != parent.path

    class ReadRouter:
        locked = False

        def db_for_read(self, model, **hints):
            if self.locked and model in (Blog, Podcast):
                return "migration_other"
            return None

    read_router = ReadRouter()
    settings.DATABASE_ROUTERS = [read_router]
    original_lock = PostEditorMixin._lock_parent_for_slug_check

    def route_after_lock(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if sql.startswith('UPDATE "wagtailcore_page" SET "numchild"'):
            read_router.locked = True
        return result

    def lock_parent(self, selected_parent, *, noun):
        with connections["default"].execute_wrapper(route_after_lock):
            try:
                locked_parent = original_lock(self, selected_parent, noun=noun)
                assert read_router.locked
                return locked_parent
            finally:
                read_router.locked = False

    monkeypatch.setattr(PostEditorMixin, "_lock_parent_for_slug_check", lock_parent)
    api_client.force_authenticate(user=admin_user)
    response = api_client.post(
        reverse(f"cast:api:editor_{kind}_create"),
        {"parent": {"id": parent.pk}, "title": "New child", "slug": "reserved-slug", "overview": []},
        format="json",
    )

    assert response.status_code == 400, response.content
    errors = response.json()["errors"]
    assert errors.get("slug", [{}])[0].get("code") == "duplicate", errors


@pytest.mark.parametrize("case", ["split_write", "split_read", "instance"])
def test_editor_refuses_split_page_routing(settings, case):
    from types import SimpleNamespace

    from cast.api.editor.errors import EditorValidationError
    from cast.api.editor.views import _page_write_database

    class SplitRouter:
        def db_for_write(self, model, **hints):
            return "migration_other" if case == "split_write" and model is Revision else "default"

        def db_for_read(self, model, **hints):
            return "migration_other" if case == "split_read" and model is Post else "default"

    settings.DATABASE_ROUTERS = [SplitRouter()]
    page = SimpleNamespace(_state=SimpleNamespace(db="migration_other")) if case == "instance" else None
    with pytest.raises(EditorValidationError) as exc:
        _page_write_database(page)
    assert "database" in exc.value.error_map


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["post", "episode"])
@pytest.mark.parametrize("operation", ["create", "patch"])
def test_editor_refuses_cross_database_user(api_client, blog, podcast, kind, operation):
    from tests.factories import EpisodeFactory, PostFactory, UserFactory

    parent = blog if kind == "post" else podcast
    user = UserFactory(is_superuser=True, is_staff=True)
    if operation == "create":
        url = reverse(f"cast:api:editor_{kind}_create")
        payload = {"parent": {"id": parent.pk}, "title": "Cross database refusal", "overview": []}
    else:
        factory = PostFactory if kind == "post" else EpisodeFactory
        page = factory(parent=parent, title="Synthetic", slug="synthetic", owner=user, live=False)
        revision = page.save_revision(user=user)
        url = reverse(f"cast:api:editor_{kind}_detail", args=[page.pk])
        payload = {"base_revision_id": revision.pk, "title": "Cross database refusal"}
    user._state.db = "migration_other"
    api_client.force_authenticate(user=user)
    response = getattr(api_client, "post" if operation == "create" else "patch")(url, payload, format="json")
    assert response.status_code == 400, response.content
    assert response.json()["errors"]["database"][0]["code"] == "unsupported"


@pytest.mark.django_db(transaction=True, databases={"default", "migration_other"})
def test_editor_error_rolls_back_atomic_request(api_client, monkeypatch):
    from cast.api.editor.errors import EditorValidationError
    from cast.api.editor.media import EditorAudioListCreateView

    alias = "migration_other"

    def post(self, request, *args, **kwargs):
        assert connections[alias].in_atomic_block
        Tag.objects.using(alias).create(name="Synthetic failed request")
        raise EditorValidationError({"title": [{"code": "invalid", "message": "Synthetic error."}]})

    monkeypatch.setitem(connections[alias].settings_dict, "ATOMIC_REQUESTS", True)
    monkeypatch.setattr(EditorAudioListCreateView, "post", post)
    api_client.force_authenticate(user=get_user_model()(is_active=True, is_staff=True, is_superuser=True))
    response = api_client.post(reverse("cast:api:editor_media_audios"), {}, format="json")

    assert response.status_code == 400, response.content
    assert response.json() == {
        "code": "validation_error",
        "errors": {"title": [{"code": "invalid", "message": "Synthetic error."}]},
    }
    assert not Tag.objects.using(alias).filter(name="Synthetic failed request").exists()


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_editor_collections_use_page_database_for_ancestors(api_client, admin_user, monkeypatch):
    from wagtail.models import Collection

    from cast.api.editor import media

    alias = "migration_other"
    default_root = Collection.get_first_root_node()
    with override_settings(DATABASE_ROUTERS=[EditorRouter()]):
        routed_root, _ = Collection.objects.update_or_create(
            path=default_root.path, defaults={"name": "Routed root", "depth": 1}
        )
        routed_first = routed_root.add_child(name="First routed collection")
        routed_second = routed_root.add_child(name="Second routed collection")
    assert routed_root.path == default_root.path
    assert routed_root.name != default_root.name

    permitted = Collection.objects.using(alias).filter(pk__in=[routed_second.pk, routed_first.pk])
    monkeypatch.setattr(media, "_usable_image_collections", lambda user: permitted)
    api_client.force_authenticate(user=admin_user)
    url = reverse("cast:api:editor_media_collections")
    for number, child in enumerate((routed_first, routed_second), start=1):
        response = api_client.get(url, {"type": "image", "pageSize": 1, "page": number})

        assert response.status_code == 200, response.content
        data = response.json()
        assert data["count"] == 2
        assert data["results"] == [
            {
                "id": child.pk,
                "name": child.name,
                "breadcrumb": f"{routed_root.name} / {child.name}",
                "ancestors": [{"id": routed_root.pk, "name": routed_root.name}],
            }
        ]


@pytest.mark.django_db(transaction=True, databases={"default", "migration_other"})
def test_editor_audio_patch_uses_one_writer(settings, api_client):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import OperationalError
    from wagtail.models import Collection

    from cast.models import Audio

    alias = "migration_other"

    class AudioRouter(EditorRouter):
        locked = False

        def db_for_read(self, model, **hints):
            if model is Audio and self.locked:
                return "default"
            return alias

    routing = AudioRouter()
    default_collection = Collection.add_root(name="Default collection")
    default_user = get_user_model().objects.create(username="default-audio-editor")
    default_audio = Audio.objects.create(
        user=default_user, collection=default_collection, title="Default audio", subtitle="Default subtitle"
    )

    settings.DATABASE_ROUTERS = [routing]
    ContentType.objects.clear_cache()
    try:
        routed_user = get_user_model().objects.create(username="routed-audio-editor", is_staff=True, is_superuser=True)
        routed_collection = Collection.add_root(name="Routed collection")
        audio = Audio.objects.create(
            pk=default_audio.pk,
            user=routed_user,
            collection=routed_collection,
            title="Routed audio",
            subtitle="Earlier subtitle",
        )
        audio.tags.add("routed-tag")

        def write_subtitle(subtitle):
            try:
                return Audio.objects.using(alias).filter(pk=audio.pk).update(subtitle=subtitle)
            finally:
                connections[alias].close()

        api_client.force_authenticate(user=routed_user)
        default_updates = []
        lock_seen = []

        def record_default_update(execute, sql, params, many, context):
            if sql.startswith('UPDATE "cast_audio"'):
                default_updates.append(sql)
            return execute(sql, params, many, context)

        with ThreadPoolExecutor(max_workers=1) as writer:

            def interleave(execute, sql, params, many, context):
                claiming = (
                    sql.startswith('UPDATE "cast_audio" SET "transcript_diarization_mode"') and not routing.locked
                )
                if claiming:
                    assert writer.submit(write_subtitle, "Concurrent subtitle").result(timeout=5) == 1
                result = execute(sql, params, many, context)
                if claiming:
                    lock_seen.append(True)
                    routing.locked = True
                    with pytest.raises(OperationalError, match="locked"):
                        writer.submit(write_subtitle, "Blocked subtitle").result(timeout=5)
                return result

            with (
                connections[alias].execute_wrapper(interleave),
                connections["default"].execute_wrapper(record_default_update),
            ):
                response = api_client.patch(
                    reverse("cast:api:editor_media_audio_detail", args=[audio.pk]),
                    {"title": "Renamed audio", "chaptermarks": "00:00:00 Routed chapter"},
                    format="json",
                )

        assert lock_seen == [True]
        assert default_updates == []
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["title"] == "Renamed audio"
        assert data["subtitle"] == "Concurrent subtitle"
        assert data["tags"] == ["routed-tag"]
        assert data["collection"] == {"id": routed_collection.pk, "name": "Routed collection"}
        audio.refresh_from_db(using=alias)
        assert audio.title == "Renamed audio"
        assert audio.subtitle == "Concurrent subtitle"
        assert list(audio.chaptermarks.using(alias).values_list("title", flat=True)) == ["Routed chapter"]
        default_audio.refresh_from_db(using="default")
        assert default_audio.title == "Default audio"
        assert default_audio.subtitle == "Default subtitle"
    finally:
        ContentType.objects.clear_cache()


@pytest.mark.django_db(databases={"default", "migration_other"})
def test_editor_audio_patch_refuses_split_writer_before_lock(settings, api_client, admin_user, audio):
    from cast.models import Audio

    class SplitRouter:
        def db_for_write(self, model, **hints):
            if model is Audio:
                return "migration_other"
            return None

    settings.DATABASE_ROUTERS = [SplitRouter()]
    api_client.force_authenticate(user=admin_user)
    updated = []

    def record_update(execute, sql, params, many, context):
        if sql.startswith('UPDATE "cast_audio"'):
            updated.append(sql)
        return execute(sql, params, many, context)

    with (
        connections["default"].execute_wrapper(record_update),
        connections["migration_other"].execute_wrapper(record_update),
    ):
        response = api_client.patch(
            reverse("cast:api:editor_media_audio_detail", args=[audio.pk]), {"title": "Wrong writer"}, format="json"
        )

    assert updated == []
    assert response.status_code == 400, response.content
    assert response.json()["errors"]["database"][0]["code"] == "unsupported"


@pytest.mark.django_db(databases={"default", "migration_other"})
@pytest.mark.parametrize("replica_model", ["collection", "tag", "contenttype"])
def test_editor_audio_patch_refuses_read_replica_routing(settings, api_client, admin_user, audio, replica_model):
    from wagtail.models import Collection

    replica_models = {"collection": Collection, "tag": Tag, "contenttype": ContentType}

    class PrimaryReplicaRouter:
        def db_for_read(self, model, **hints):
            return "migration_other" if model is replica_models[replica_model] else "default"

        def db_for_write(self, model, **hints):
            return "default"

    original_title = audio.title
    settings.DATABASE_ROUTERS = [PrimaryReplicaRouter()]
    ContentType.objects.clear_cache()
    api_client.force_authenticate(user=admin_user)
    updated = []

    def record_update(execute, sql, params, many, context):
        if sql.startswith('UPDATE "cast_audio"'):
            updated.append(sql)
        return execute(sql, params, many, context)

    try:
        with (
            connections["default"].execute_wrapper(record_update),
            connections["migration_other"].execute_wrapper(record_update),
        ):
            response = api_client.patch(
                reverse("cast:api:editor_media_audio_detail", args=[audio.pk]), {"title": "Replica"}, format="json"
            )
    finally:
        ContentType.objects.clear_cache()

    assert updated == []
    assert response.status_code == 400, response.content
    assert response.json()["errors"]["database"][0]["code"] == "unsupported"
    audio.refresh_from_db(using="default")
    assert audio.title == original_title
