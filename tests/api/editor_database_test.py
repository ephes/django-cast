"""Real editor writes on an independent, fully routed synthetic database."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from taggit.models import Tag
from wagtail.models import Locale, Page, Revision

from cast.api.editor.views import PostEditorMixin
from cast.models import Blog, Episode, Podcast, Post
from tests.factories import EpisodeFactory, PostFactory


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
