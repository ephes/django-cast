import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.urls import reverse

from cast.admin import (
    AdminUserMixin,
    SpamfilterModelAdmin,
    VideoModelAdmin,
    cache_file_sizes,
    retrain,
)
from cast.models import Contributor, ContributorLink, EpisodeContributor, SpamFilter, Video
from cast.wagtail_hooks import ContributorMenuItem, register_contributor_menu_item


def test_spamfilter_model_admin():
    expected_performance = {
        "spam": {"precision": 0.5, "recall": 0.5},
        "ham": {"precision": 0.5, "recall": 0.5},
    }
    spamfilter = SpamFilter(performance=expected_performance)
    sma = SpamfilterModelAdmin(SpamFilter, None)
    assert sma.spam(spamfilter) == expected_performance["spam"]
    assert sma.ham(spamfilter) == expected_performance["ham"]


class SpySpamfilter:
    got_training_data = False
    retrained = False

    def get_training_data_comments(self):
        self.got_training_data = True
        return []

    def retrain_from_scratch(self, train):
        self.retrained = True


def test_retrain():
    spy = SpySpamfilter()
    retrain(None, None, [spy])
    assert spy.got_training_data
    assert spy.retrained


@pytest.mark.django_db
def test_video_model_admin_calc_poster(mocker):
    class MockedForm:
        cleaned_data = {"poster": False}

    mocked_super = mocker.patch("cast.admin.ModelAdmin.save_model")
    vma = VideoModelAdmin(Video, None)

    # change=True, poster=False -> calc_poster=False
    vma.save_model(None, Video(), MockedForm(), True)
    processed_video = mocked_super.call_args[0][1]
    assert not processed_video.calc_poster

    # change=False, poster=False -> calc_poster=True
    vma.save_model(None, Video(), MockedForm(), False)
    processed_video = mocked_super.call_args[0][1]
    assert processed_video.calc_poster


def test_cache_file_sizes():
    class SpyAudio:
        cached = False

        def size_to_metadata(self):
            self.cached = True

        def save(self):
            pass

    spy = SpyAudio()
    cache_file_sizes(None, None, [spy])
    assert spy.cached


def test_admin_user_mixin():
    class SpyRequest:
        user = "foobar"

    aum = AdminUserMixin()
    initial_data = aum.get_changeform_initial_data(SpyRequest())
    assert initial_data == {"user": SpyRequest.user, "author": SpyRequest.user}


def test_register_contributor_menu_item():
    item = register_contributor_menu_item()

    assert isinstance(item, ContributorMenuItem)
    assert str(item.label) == "Contributors"
    assert item.url == reverse("wagtailsnippets_cast_contributor:list")
    assert item.name == "contributors"
    assert item.icon_name == "group"
    assert item.order == 210


@pytest.mark.django_db
def test_contributor_menu_item_visibility_requires_snippet_permission(user):
    item = ContributorMenuItem("Contributors", reverse("wagtailsnippets_cast_contributor:list"))
    request = RequestFactory().get("/")
    request.user = AnonymousUser()

    assert not item.is_shown(request)

    request.user = user
    assert not item.is_shown(request)

    content_type = ContentType.objects.get_for_model(Contributor)
    permission = Permission.objects.get(content_type=content_type, codename="view_contributor")
    user.user_permissions.add(permission)
    for cache_name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        if hasattr(user, cache_name):
            delattr(user, cache_name)

    assert item.is_shown(request)


@pytest.mark.django_db
def test_contributor_link_options(admin_client):
    contributor = Contributor.objects.create(
        display_name="Guest",
        slug="guest",
        default_role=EpisodeContributor.ROLE_HOST,
    )
    other_contributor = Contributor.objects.create(display_name="Other Guest", slug="other-guest")
    unordered_link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_YOUTUBE,
        url="https://example.com/youtube",
    )
    second_link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_MASTODON,
        url="https://example.com/mastodon",
        sort_order=2,
    )
    first_link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/guest",
        sort_order=1,
    )
    ContributorLink.objects.create(
        contributor=other_contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/other",
    )

    response = admin_client.get(reverse("cast-contributors:links"), {"contributor_id": contributor.pk})

    assert response.status_code == 200
    assert response.json() == {
        "defaultLinkId": str(first_link.pk),
        "defaultRole": EpisodeContributor.ROLE_HOST,
        "links": [
            {
                "contributorId": str(contributor.pk),
                "text": "Guest: Website",
                "value": str(first_link.pk),
            },
            {
                "contributorId": str(contributor.pk),
                "text": "Guest: Mastodon",
                "value": str(second_link.pk),
            },
            {
                "contributorId": str(contributor.pk),
                "text": "Guest: YouTube",
                "value": str(unordered_link.pk),
            },
        ],
    }


@pytest.mark.django_db
def test_contributor_link_options_with_invalid_contributor_id(admin_client):
    response = admin_client.get(reverse("cast-contributors:links"), {"contributor_id": "invalid"})

    assert response.status_code == 200
    assert response.json() == {"defaultLinkId": "", "defaultRole": "", "links": []}


@pytest.mark.django_db
def test_contributor_link_options_requires_contributor_snippet_permission(client):
    contributor = Contributor.objects.create(display_name="Guest", slug="guest")
    link = ContributorLink.objects.create(
        contributor=contributor,
        service=ContributorLink.SERVICE_WEBSITE,
        url="https://example.com/guest",
    )
    user = get_user_model().objects.create_user(
        username="contributor-link-options-admin",
        password="password",
        is_staff=True,
    )
    access_admin = Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
    user.user_permissions.add(access_admin)
    assert client.login(username="contributor-link-options-admin", password="password")

    response = client.get(reverse("cast-contributors:links"), {"contributor_id": contributor.pk})

    assert response.status_code == 403
    assert response.json() == {"defaultLinkId": "", "defaultRole": "", "links": []}

    view_contributor = Permission.objects.get(
        content_type=ContentType.objects.get_for_model(Contributor),
        codename="view_contributor",
    )
    user.user_permissions.add(view_contributor)
    for cache_name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        if hasattr(user, cache_name):
            delattr(user, cache_name)

    response = client.get(reverse("cast-contributors:links"), {"contributor_id": contributor.pk})

    assert response.status_code == 200
    assert response.json() == {
        "defaultLinkId": str(link.pk),
        "defaultRole": EpisodeContributor.ROLE_GUEST,
        "links": [
            {
                "contributorId": str(contributor.pk),
                "text": "Guest: Website",
                "value": str(link.pk),
            }
        ],
    }
