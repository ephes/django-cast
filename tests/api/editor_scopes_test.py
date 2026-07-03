# ruff: noqa: F401,F811,I001
import json
import subprocess

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from wagtail.models import Collection, GroupCollectionPermission, GroupPagePermission, Page

from cast import media_probe
from cast.api.editor import media as editor_media
from cast.api.editor.body import (
    SUPPORTED_OVERVIEW_BLOCKS,
    _media_ref_is_available,
    author_blocks_to_overview,
    overview_to_author_blocks,
)
from cast.api.editor.errors import (
    EditorNotFound,
    EditorPermissionDenied,
    EditorValidationError,
    editor_exception_handler,
)
from cast.models import Audio, Episode, Post, Season, Video
from cast.models.snippets import PostCategory

from tests.factories import BlogFactory, EpisodeFactory, PodcastFactory, PostFactory, UserFactory


def grant_wagtail_admin_access(user) -> None:
    permission = Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
    user.user_permissions.add(permission)


def grant_collection_permission(user, collection, *, app_label: str, codename: str) -> None:
    group = Group.objects.create(name=f"Collection permission {user.pk} {codename} {collection.pk}")
    permission = Permission.objects.get(codename=codename, content_type__app_label=app_label)
    GroupCollectionPermission.objects.create(group=group, collection=collection, permission=permission)
    user.groups.add(group)


def page_permission_user(*, codenames: tuple[str, ...]) -> object:
    user = UserFactory(is_staff=True)
    group = Group.objects.create(name=f"Page permissions {user.pk}")
    root_page = Page.get_first_root_node()
    assert root_page is not None
    for codename in codenames:
        permission = Permission.objects.get(codename=codename, content_type__app_label="wagtailcore")
        GroupPagePermission.objects.create(group=group, page=root_page, permission=permission)
    user.groups.add(group)
    return user


@pytest.fixture
def superuser(django_user_model):
    """A superuser, which passes every Wagtail page and image ``choose`` permission."""
    return django_user_model.objects.create_superuser(
        username="editor-su", email="editor-su@example.com", password="password"
    )


class TestEditorScopeReader:
    def test_none_auth_returns_none(self):
        from cast.api.editor.scopes import get_request_scopes

        assert get_request_scopes(None) is None

    def test_space_separated_scope_string_is_split(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": "write publish"})()
        assert get_request_scopes(token) == {"write", "publish"}

    def test_scopes_iterable_is_collected(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": ["write"]})()
        assert get_request_scopes(token) == {"write"}

    def test_token_without_scope_info_returns_none(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {})()
        assert get_request_scopes(token) is None

    def test_empty_scope_string_is_empty_set_not_none(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": ""})()
        assert get_request_scopes(token) == set()

    def test_non_string_scope_value_fails_closed(self):
        # ``scope`` is string-only by convention; a list must NOT be coerced into granted
        # scopes (that would fail open). It fails closed to an empty set.
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scope": ["write"]})()
        assert get_request_scopes(token) == set()

    def test_empty_scopes_iterable_is_empty_set(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": []})()
        assert get_request_scopes(token) == set()

    def test_non_iterable_scopes_value_fails_closed(self):
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": 1})()
        assert get_request_scopes(token) == set()

    def test_scopes_accepts_any_non_string_iterable(self):
        # The contract is "iterable of scope strings", not "list" — a generator works.
        from cast.api.editor.scopes import get_request_scopes

        token = type("Tok", (), {"scopes": iter(["write", "publish"])})()
        assert get_request_scopes(token) == {"write", "publish"}


class TestHasEditorScope:
    def _request(self, method, auth):
        return type("Req", (), {"method": method, "auth": auth})()

    def _view(self, required_scopes):
        # Model a view that actually serves get/post/patch so the ``hasattr`` handler
        # check passes; behavior here is driven by ``required_scopes`` (the 405
        # fall-through for genuinely-unimplemented methods is covered by the API tests).
        def handler(self, *args, **kwargs):
            return None

        attrs = {"required_scopes": required_scopes, "get": handler, "post": handler, "patch": handler}
        return type("View", (), attrs)()

    def test_options_is_allowed_without_declaration(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        assert perm.has_permission(self._request("OPTIONS", None), self._view({})) is True

    def test_none_scope_method_is_allowed(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        assert perm.has_permission(self._request("GET", None), self._view({"GET": None})) is True

    def test_undeclared_method_fails_closed(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        with pytest.raises(EditorFlatError) as exc:
            perm.has_permission(self._request("PATCH", None), self._view({"GET": None}))
        assert exc.value.code_text == "insufficient_scope"
        assert exc.value.status_code == 403

    def test_session_request_allows_write(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        # request.auth is None (session) -> defer to Wagtail
        assert perm.has_permission(self._request("POST", None), self._view({"POST": "write"})) is True

    def test_unscoped_token_allows_write(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {})()  # no scope/scopes attribute
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "write"})) is True

    def test_scoped_token_missing_scope_is_denied(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "publish"})()  # has publish, needs write
        with pytest.raises(EditorFlatError) as exc:
            perm.has_permission(self._request("POST", token), self._view({"POST": "write"}))
        assert exc.value.code_text == "insufficient_scope"

    def test_write_scope_allows_write_but_not_publish(self):
        from cast.api.editor.errors import EditorFlatError
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "write"})()
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "write"})) is True
        with pytest.raises(EditorFlatError):
            perm.has_permission(self._request("POST", token), self._view({"POST": "publish"}))

    def test_publish_scope_allows_publish(self):
        from cast.api.editor.scopes import HasEditorScope

        perm = HasEditorScope()
        token = type("Tok", (), {"scope": "publish"})()
        assert perm.has_permission(self._request("POST", token), self._view({"POST": "publish"})) is True


class TestEditorViewScopeDeclarations:
    pytestmark = pytest.mark.django_db

    def _editor_views(self):
        from cast.api import urls as api_urls

        views = {}
        for pattern in api_urls.urlpatterns:
            name = getattr(pattern, "name", None) or ""
            if not name.startswith("editor_"):
                continue
            cls = getattr(pattern.callback, "cls", None)
            if cls is not None:
                views[name] = cls
        return views

    def test_found_editor_views(self):
        # Guards the guard: make sure the URLconf scan actually finds the views.
        assert "editor_post_create" in self._editor_views()
        assert "editor_episode_publish" in self._editor_views()

    def test_every_served_method_declares_a_required_scope(self):
        valid = {None, "write", "publish"}
        skipped = {"options", "head", "trace"}
        for name, cls in self._editor_views().items():
            methods = [m for m in cls.http_method_names if m not in skipped and hasattr(cls, m)]
            assert methods, f"{name}: no handler methods found"
            for method in methods:
                key = method.upper()
                assert key in cls.required_scopes, f"{name} ({cls.__name__}) does not declare scope for {key}"
                assert cls.required_scopes[key] in valid, f"{name}: bad scope value for {key}"


class _FakeScopedToken:
    def __init__(self, scope: str):
        self.scope = scope


class TestEditorScopeEnforcement:
    pytestmark = pytest.mark.django_db

    def _create_draft(self, api_client, blog, user):
        api_client.force_authenticate(user=user)
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Scope draft",
            "slug": "scope-draft",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def test_session_request_can_read(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        # session auth: request.auth is None -> scope layer defers to Wagtail
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        assert api_client.get(url, format="json").status_code == 200

    def test_unscoped_token_can_write(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user, token=type("Tok", (), {})())
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Unscoped write",
            "slug": "unscoped-write",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201

    def test_write_scope_can_create(self, api_client, blog, admin_user):
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("write"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Write scope",
            "slug": "write-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201

    def test_missing_scope_is_403_insufficient_scope(self, api_client, blog, admin_user):
        # Token carries 'publish' but creating requires 'write'.
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "No write scope",
            "slug": "no-write-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        response = api_client.post(url, payload, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_scope"
        assert not Post.objects.filter(slug="no-write-scope").exists()

    def test_write_scope_cannot_publish(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("write"))
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})
        response = api_client.post(url, {}, format="json")
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_scope"
        assert Post.objects.get(pk=created["id"]).live is False

    def test_publish_scope_can_publish(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_publish", kwargs={"pk": created["id"]})
        response = api_client.post(url, {}, format="json")
        assert response.status_code == 200, response.content
        assert Post.objects.get(pk=created["id"]).live is True

    def test_scoped_token_can_read_without_scope(self, api_client, blog, admin_user):
        created = self._create_draft(api_client, blog, admin_user)
        # A token scoped only for publish can still GET (reads need no scope).
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("publish"))
        url = reverse("cast:api:editor_post_detail", kwargs={"pk": created["id"]})
        assert api_client.get(url, format="json").status_code == 200

    def test_cast_editor_scopes_override_is_honoured(self, api_client, blog, admin_user, settings):
        # Rename the write scope to match a site's issuer vocabulary.
        settings.CAST_EDITOR_SCOPES = {"write": {"posts:edit"}, "publish": {"publish"}}
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("posts:edit"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "Custom scope",
            "slug": "custom-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201

    def test_list_valued_scope_setting_is_honoured(self, api_client, blog, admin_user, settings):
        # Operators naturally write lists; the scope check must not 500 on a non-set value.
        settings.CAST_EDITOR_SCOPES = {"write": ["posts:edit"], "publish": ["publish"]}
        api_client.force_authenticate(user=admin_user, token=_FakeScopedToken("posts:edit"))
        url = reverse("cast:api:editor_post_create")
        payload = {
            "parent": {"id": blog.id},
            "title": "List scope",
            "slug": "list-scope",
            "tags": [],
            "overview": [{"type": "heading", "value": "Notes"}],
        }
        assert api_client.post(url, payload, format="json").status_code == 201

    def test_unsupported_method_is_405_not_403(self, api_client, admin_user):
        # GET on a POST-only view must return 405 Method Not Allowed, not a scope 403.
        api_client.force_authenticate(user=admin_user)
        response = api_client.get(reverse("cast:api:editor_post_create"), format="json")
        assert response.status_code == 405
