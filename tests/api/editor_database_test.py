"""Real editor writes on an independent, fully routed synthetic database."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connections
from django.urls import reverse
from taggit.models import Tag
from wagtail.models import Locale, Page, Revision

from cast.models import Blog, Podcast, Post


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
