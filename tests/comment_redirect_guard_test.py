"""The comments redirect only reveals URLs of pages the requester may view."""

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django_comments import get_model
from wagtail.models import GroupPagePermission, Page, PageViewRestriction

from .factories import UserFactory

pytestmark = pytest.mark.django_db


def redirect_url(obj, pk=None):
    content_type = ContentType.objects.get_for_model(obj)
    return reverse("comments-url-redirect", args=(content_type.pk, obj.pk if pk is None else pk))


def test_public_post_redirects_to_page_url(client, post):
    response = client.get(redirect_url(post))
    assert response.status_code == 302
    assert response["Location"] == post.get_url()


def test_generic_page_content_type_redirects_for_public_post(client, post):
    page = Page.objects.get(pk=post.pk)
    response = client.get(redirect_url(page))
    assert response.status_code == 302
    assert response["Location"] == post.get_url()


def test_unpublished_post_is_not_found(client, post):
    post.unpublish()
    response = client.get(redirect_url(post))
    assert response.status_code == 404
    assert "Location" not in response


@pytest.mark.parametrize("restriction_type", ["login", "groups", "password"])
def test_view_restricted_post_is_not_found(client, post, restriction_type):
    restriction = PageViewRestriction.objects.create(page=post, restriction_type=restriction_type, password="secret")
    if restriction_type == "groups":
        restriction.groups.add(Group.objects.create(name="members"))
    response = client.get(redirect_url(post))
    assert response.status_code == 404


def test_post_restricted_through_ancestor_is_not_found(client, post):
    PageViewRestriction.objects.create(page=post.get_parent(), restriction_type="login")
    response = client.get(redirect_url(post))
    assert response.status_code == 404


def test_login_restricted_post_redirects_for_logged_in_user(authenticated_client, post):
    PageViewRestriction.objects.create(page=post, restriction_type="login")
    response = authenticated_client.get(redirect_url(post))
    assert response.status_code == 302
    assert response["Location"] == post.get_url()


def test_unpublished_post_redirects_for_editor(client, post):
    editor = UserFactory()
    group = Group.objects.create(name="editors")
    GroupPagePermission.objects.create(group=group, page=post.get_parent(), permission_type="change")
    editor.groups.add(group)
    client.force_login(editor)
    post.unpublish()
    response = client.get(redirect_url(post))
    assert response.status_code == 302


def test_unpublished_post_is_not_found_for_non_editor(client, post):
    client.force_login(UserFactory())
    post.unpublish()
    response = client.get(redirect_url(post))
    assert response.status_code == 404


def test_user_content_type_is_not_found(client, user):
    response = client.get(redirect_url(user))
    assert response.status_code == 404
    assert "Location" not in response


def test_non_page_content_type_is_not_found_for_superuser(admin_client, admin_user):
    response = admin_client.get(redirect_url(admin_user))
    assert response.status_code == 404


def test_non_numeric_pk_is_not_found(client, post):
    response = client.get(redirect_url(post, pk="not-a-pk"))
    assert response.status_code == 404


def test_missing_pk_is_not_found(client, post):
    response = client.get(redirect_url(post, pk=post.pk + 1000))
    assert response.status_code == 404


def test_unknown_content_type_is_not_found(client):
    response = client.get(reverse("comments-url-redirect", args=(999999, 1)))
    assert response.status_code == 404


def test_stale_content_type_is_not_found(client):
    stale = ContentType.objects.create(app_label="gone", model="removed")
    response = client.get(reverse("comments-url-redirect", args=(stale.pk, 1)))
    assert response.status_code == 404


def test_comment_permalink_for_public_post(client, post, comments_enabled):
    comment = get_model().objects.create(
        content_object=post, site_id=1, comment="hello", user_name="Visitor", is_public=True
    )
    permalink = comment.get_absolute_url()
    path, fragment = permalink.split("#")
    assert path == redirect_url(post)
    assert fragment == f"c{comment.pk}"
    # Browsers keep the fragment across the redirect, so it lands on the comment.
    response = client.get(path)
    assert response.status_code == 302
    assert response["Location"] == post.get_url()


def test_live_page_without_routable_url_is_not_found(client, post, monkeypatch):
    # A live page outside every Wagtail site has no URL to redirect to.
    monkeypatch.setattr(type(post), "get_url", lambda self, request=None, current_site=None: None)
    response = client.get(redirect_url(post))
    assert response.status_code == 404
