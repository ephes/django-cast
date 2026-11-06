"""Private API responses must recheck access even with full-site caching."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.urls import reverse
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from wagtail.models import GroupPagePermission

from cast.api.editor.views import EditorAPIView
from cast.api.views import AudioDetailView, AudioListView, VideoDetailView, VideoListView
from cast.models import Audio, SpamFilter, Video
from tests.factories import PostFactory


class SyntheticBearerAuthentication(BaseAuthentication):
    """Resolve synthetic credentials from current DB state on every request."""

    def authenticate(self, request):
        value = request.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            return None
        user = get_user_model().objects.filter(username=value.removeprefix("Bearer "), is_active=True).first()
        if user is None:
            raise AuthenticationFailed("Revoked synthetic credential.")
        return user, None


@pytest.fixture
def full_site_cache(settings):
    settings.MIDDLEWARE = [
        "django.middleware.cache.UpdateCacheMiddleware",
        *settings.MIDDLEWARE,
        "django.middleware.cache.FetchFromCacheMiddleware",
    ]
    settings.CACHE_MIDDLEWARE_SECONDS = 60
    cache.clear()
    yield
    cache.clear()


def assert_private(response):
    assert response["Cache-Control"] == "private, no-store"
    assert {"Cookie", "Authorization"} <= {value.strip() for value in response["Vary"].split(",")}


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["audio", "video"])
@pytest.mark.parametrize("detail", [False, True])
def test_owner_media_rechecks_revoked_bearer(client, full_site_cache, monkeypatch, user, admin_user, kind, detail):
    views = (AudioListView, AudioDetailView) if kind == "audio" else (VideoListView, VideoDetailView)
    for view in views:
        monkeypatch.setattr(view, "authentication_classes", (SyntheticBearerAuthentication,))
    if kind == "audio":
        media = Audio(user=user, title="Synthetic private audio")
        media.save(duration=False, cache_file_sizes=False)
    else:
        media = Video.objects.create(user=user, title="Synthetic private video", original="synthetic.mp4")
    url = reverse(f"cast:api:{kind}_{'detail' if detail else 'list'}", kwargs={"pk": media.pk} if detail else {})
    headers = {"HTTP_AUTHORIZATION": f"Bearer {user.username}"}
    response = client.get(url, **headers)
    assert response.status_code == 200
    marker = media.title.encode() if kind == "audio" else b"synthetic.mp4"
    assert marker in response.content

    other = client.get(url, HTTP_AUTHORIZATION=f"Bearer {admin_user.username}")
    assert other.status_code == (404 if detail else 200)
    assert marker not in other.content

    user.is_active = False
    user.save(update_fields=["is_active"])
    revoked = client.get(url, **headers)
    assert revoked.status_code == 403
    assert marker not in revoked.content
    assert_private(other)
    assert_private(response)
    assert_private(revoked)
    assert_private(client.get(url))


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["editor_parents", "editor_post_detail", "editor_post_preview"])
def test_editor_rechecks_permission_after_warming_cache(client, full_site_cache, monkeypatch, user, blog, endpoint):
    monkeypatch.setattr(EditorAPIView, "authentication_classes", (SyntheticBearerAuthentication,))
    permission = Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
    user.user_permissions.add(permission)
    group = Group.objects.create(name="Synthetic page editors")
    change = Permission.objects.get(codename="change_page", content_type__app_label="wagtailcore")
    GroupPagePermission.objects.create(group=group, page=blog, permission=change)
    user.groups.add(group)
    post = PostFactory(parent=blog, owner=user, title="Synthetic unpublished secret", slug="private-draft", live=False)
    post.save_revision(user=user)
    kwargs = {} if endpoint == "editor_parents" else {"pk": post.pk}
    url = reverse(f"cast:api:{endpoint}", kwargs=kwargs)
    headers = {"HTTP_AUTHORIZATION": f"Bearer {user.username}"}
    response = client.get(url, **headers)
    assert response.status_code == 200, response.content
    if endpoint != "editor_parents":
        assert post.title.encode() in response.content

    user.user_permissions.remove(permission)
    denied = client.get(url, **headers)
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"
    assert post.title.encode() not in denied.content
    assert_private(response)
    assert_private(denied)

    missing = client.get(reverse("cast:api:editor_post_detail", kwargs={"pk": 999999}), **headers)
    assert missing.status_code == 403
    assert_private(missing)


@pytest.mark.django_db
@pytest.mark.parametrize("revoke", ["staff", "session"])
def test_training_corpus_is_not_cached_after_staff_access_is_revoked(
    client, full_site_cache, monkeypatch, admin_user, revoke
):
    corpus = [["ham", "Synthetic private moderation message"]]
    monkeypatch.setattr(SpamFilter, "get_training_data_comments", lambda: corpus)
    client.force_login(admin_user)
    url = reverse("cast:api:comment-training-data")
    response = client.get(url)
    assert response.status_code == 200
    assert response.json() == corpus
    if revoke == "staff":
        admin_user.is_staff = False
        admin_user.save(update_fields=["is_staff"])
    else:
        client.session.flush()
    denied = client.get(url)
    assert denied.status_code == 403
    assert b"Synthetic private moderation message" not in denied.content
    assert_private(response)
    assert_private(denied)
