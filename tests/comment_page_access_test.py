"""A signed comment form does not preserve revoked page access."""

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django_comments import get_form, get_model
from wagtail.models import PageViewRestriction

from .factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["comments-post-comment", "comments-post-comment-ajax"])
def comment_endpoint(request):
    return request.param


@pytest.fixture(params=[False, True], ids=["create", "preview"])
def preview(request):
    return request.param


def comment_payload(target, preview):
    form = get_form()(target)
    data = {name: str(form[name].value()) for name in ("content_type", "object_pk", "timestamp", "security_hash")}
    data.update(comment="Still allowed?", name="Visitor", email="visitor@example.com", title="Comment")
    if preview:
        data["preview"] = "1"
    return data


def submit(client, endpoint, data):
    return client.post(reverse(endpoint), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")


@pytest.mark.parametrize("revocation", ["unpublish", "login", "groups", "password", "inherited_login"])
def test_retained_public_form_rejected_after_access_revocation(
    client, post, comments_enabled, comment_endpoint, preview, revocation
):
    # Obtain the real signed fields while the page is publicly accessible.
    page_url = post.get_url()
    response = client.get(page_url)
    assert response.status_code == 200
    form = response.context["form"]
    data = comment_payload(post, preview)
    for name in ("content_type", "object_pk", "timestamp", "security_hash"):
        data[name] = str(form[name].value())

    if revocation == "unpublish":
        post.unpublish()
    else:
        target = post.get_parent() if revocation == "inherited_login" else post
        restriction_type = "login" if revocation == "inherited_login" else revocation
        PageViewRestriction.objects.create(page=target, restriction_type=restriction_type, password="secret")

    inaccessible_page = client.get(page_url)
    assert inaccessible_page.status_code in (200, 302, 404)
    # Password protection renders a challenge; it must not render the page's comment form.
    if inaccessible_page.status_code == 200:
        assert inaccessible_page.template_name == "wagtailcore/password_required.html"
    before = get_model().objects.count()
    response = submit(client, comment_endpoint, data)
    assert response.status_code == 403
    assert get_model().objects.count() == before


@pytest.mark.parametrize("restriction_type", ["login", "groups", "password"])
@pytest.mark.parametrize("inherited", [False, True], ids=["direct", "inherited"])
def test_authorized_restricted_viewers_can_comment(
    client, post, comments_enabled, comment_endpoint, preview, restriction_type, inherited
):
    restriction = PageViewRestriction.objects.create(
        page=post.get_parent() if inherited else post, restriction_type=restriction_type, password="secret"
    )
    if restriction_type == "password":
        session = client.session
        session[restriction.passed_view_restrictions_session_key] = [restriction.pk]
        session.save()
    else:
        user = UserFactory()
        if restriction_type == "groups":
            group = Group.objects.create(name="Page readers")
            user.groups.add(group)
            restriction.groups.add(group)
        client.force_login(user)
    assert client.get(post.get_url()).status_code == 200
    before = get_model().objects.count()
    response = submit(client, comment_endpoint, comment_payload(post, preview))
    assert response.status_code == (302 if not preview and comment_endpoint == "comments-post-comment" else 200)
    assert get_model().objects.count() == before + (not preview)


def test_generic_comment_targets_keep_existing_policy(client, comment_endpoint, preview):
    target = Group.objects.create(name="Generic comment target")
    before = get_model().objects.count()
    response = submit(client, comment_endpoint, comment_payload(target, preview))
    assert response.status_code == (302 if not preview and comment_endpoint == "comments-post-comment" else 200)
    assert get_model().objects.count() == before + (not preview)


def test_direct_restriction_access_does_not_bypass_inherited_restriction(
    client, post, comments_enabled, comment_endpoint, preview
):
    user = UserFactory()
    client.force_login(user)
    PageViewRestriction.objects.create(page=post, restriction_type="login")
    data = comment_payload(post, preview)
    PageViewRestriction.objects.create(page=post.get_parent(), restriction_type="groups")
    before = get_model().objects.count()
    response = submit(client, comment_endpoint, data)
    assert response.status_code == 403
    assert get_model().objects.count() == before


def test_superuser_cannot_comment_on_unpublished_page(client, post, comments_enabled, comment_endpoint, preview):
    client.force_login(UserFactory(is_superuser=True, is_staff=True))
    data = comment_payload(post, preview)
    post.unpublish()
    before = get_model().objects.count()
    response = submit(client, comment_endpoint, data)
    assert response.status_code == 403
    assert get_model().objects.count() == before
