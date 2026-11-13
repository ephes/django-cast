import pytest
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from wagtail.models import GroupPagePermission, Page, Revision

from cast.api.editor.views import PostEditorMixin
from cast.models import Post
from tests.factories import UserFactory


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["post", "episode"])
@pytest.mark.parametrize("change", ["withdraw", "move"])
def test_create_rechecks_current_parent_authority(api_client, blog, podcast, monkeypatch, kind, change):
    parent = blog if kind == "post" else podcast
    user = UserFactory(is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin"))
    group = Group.objects.create(name="Synthetic creator")
    user.groups.add(group)
    permission = Permission.objects.get(codename="add_page", content_type__app_label="wagtailcore")
    # Grant on the current ancestor so moving the parent revokes the inherited grant.
    from tests.factories import BlogFactory

    ancestor = BlogFactory(parent=Page.get_first_root_node())
    parent.move(ancestor, pos="last-child")
    parent.refresh_from_db()
    grant = GroupPagePermission.objects.create(group=group, page=ancestor, permission=permission)
    original = PostEditorMixin._lock_parent_for_slug_check

    def change_before_lock(self, selected_parent, *, noun):
        if change == "withdraw":
            grant.delete()
        else:
            from tests.factories import BlogFactory

            destination = BlogFactory(parent=Page.get_first_root_node())
            selected_parent.move(destination, pos="last-child")
        return original(self, selected_parent, noun=noun)

    monkeypatch.setattr(PostEditorMixin, "_lock_parent_for_slug_check", change_before_lock)
    api_client.force_authenticate(user=user)
    before = Post.objects.count(), Revision.objects.count()
    response = api_client.post(
        reverse(f"cast:api:editor_{kind}_create"),
        {
            "parent": {"id": parent.pk},
            "title": "Synthetic refusal",
            "slug": "synthetic-refusal",
            "tags": ["never-written"],
            "overview": [{"type": "paragraph", "value": "<p>Example</p>"}],
        },
        format="json",
    )
    assert response.status_code == 403, response.content
    assert (Post.objects.count(), Revision.objects.count()) == before
    assert not Page.objects.filter(slug="synthetic-refusal").exists()
    from taggit.models import Tag

    assert not Tag.objects.filter(name="never-written").exists()


@pytest.mark.parametrize("kind", ["post", "episode"])
@pytest.mark.parametrize("change", ["withdraw", "move"])
def test_create_rechecks_separate_connection_changes(pg_editor_actors, api_client, monkeypatch, kind, change):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import close_old_connections, connection

    from tests.factories import BlogFactory, PodcastFactory

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL separate-connection parent authority regression")
    _, blog = pg_editor_actors
    ancestor = BlogFactory(parent=blog.get_parent())
    factory = BlogFactory if kind == "post" else PodcastFactory
    parent = factory(parent=ancestor)
    user = UserFactory(is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin"))
    group = Group.objects.create(name="Synthetic concurrent creator")
    user.groups.add(group)
    grant = GroupPagePermission.objects.create(
        group=group,
        page=ancestor,
        permission=Permission.objects.get(codename="add_page", content_type__app_label="wagtailcore"),
    )
    destination = BlogFactory(parent=blog.get_parent())
    original = PostEditorMixin._lock_parent_for_slug_check

    def revoke():
        close_old_connections()
        try:
            if change == "withdraw":
                GroupPagePermission.objects.filter(pk=grant.pk).delete()
            else:
                selected = Page.objects.get(pk=parent.pk).specific
                selected.move(Page.objects.get(pk=destination.pk), pos="last-child")
        finally:
            close_old_connections()

    def before_lock(self, selected_parent, *, noun):
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(revoke).result(timeout=10)
        return original(self, selected_parent, noun=noun)

    monkeypatch.setattr(PostEditorMixin, "_lock_parent_for_slug_check", before_lock)
    before = Post.objects.count(), Revision.objects.count()
    api_client.force_authenticate(user=user)
    response = api_client.post(
        reverse(f"cast:api:editor_{kind}_create"),
        {
            "parent": {"id": parent.pk},
            "title": "Concurrent refusal",
            "overview": [],
            "tags": ["concurrent-never-written"],
        },
        format="json",
    )
    assert response.status_code == 403, response.content
    assert (Post.objects.count(), Revision.objects.count()) == before
    assert not Page.objects.filter(slug="concurrent-refusal").exists()
