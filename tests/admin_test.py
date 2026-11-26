import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from cast.admin import (
    AdminUserMixin,
    AudioAdmin,
    SpamfilterModelAdmin,
    VideoModelAdmin,
    cache_file_sizes,
    retrain,
)
from cast.models import Audio, Contributor, ContributorLink, EpisodeContributor, SpamFilter, Video
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

    def retrain_from_scratch(self):
        self.get_training_data_comments()
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

    save_video = mocker.patch("cast.admin.save_video_with_derivations")
    vma = VideoModelAdmin(Video, None)

    # change=True, poster=False -> calc_poster=False
    vma.save_model(None, Video(), MockedForm(), True)
    processed_video = save_video.call_args.args[0]
    assert not processed_video.calc_poster

    # change=False, poster=False -> calc_poster=True
    vma.save_model(None, Video(), MockedForm(), False)
    processed_video = save_video.call_args.args[0]
    assert processed_video.calc_poster


@pytest.mark.django_db
def test_cache_file_sizes_refreshes_stored_sizes(audio):
    Audio.objects.filter(pk=audio.pk).update(data={"size": {"m4a": 1}, "size_file_names": {"m4a": audio.m4a.name}})

    cache_file_sizes(None, None, Audio.objects.filter(pk=audio.pk))

    audio.refresh_from_db()
    assert audio.data["size"] == {"m4a": audio.m4a.size}
    assert audio.data["size_file_names"] == {"m4a": audio.m4a.name}


@pytest.mark.django_db
def test_cache_file_sizes_keeps_editor_saves_made_during_the_probe(audio, mocker):
    original_name = audio.m4a.name
    stale = Audio.objects.get(pk=audio.pk)
    stale.data = {"size": {"m4a": 1}, "size_file_names": {"m4a": original_name}}
    newer_data = {
        "editor": "kept",
        "size": {"m4a": 999, "mp3": 5},
        "size_file_names": {"m4a": "cast_audio/replacement.m4a", "mp3": "cast_audio/other.mp3"},
    }

    def editor_saves_during_probe(name):
        Audio.objects.filter(pk=audio.pk).update(
            title="edited title", m4a="cast_audio/replacement.m4a", mp3="cast_audio/other.mp3", data=newer_data
        )
        return 123

    mocker.patch.object(stale.m4a.storage, "size", side_effect=editor_saves_during_probe)

    cache_file_sizes(None, None, [stale])

    current = Audio.objects.get(pk=audio.pk)
    assert current.title == "edited title"
    assert current.m4a.name == "cast_audio/replacement.m4a"
    assert current.mp3.name == "cast_audio/other.mp3"
    assert current.data == newer_data


@pytest.mark.django_db
def test_cache_file_sizes_merges_only_probed_size_keys(audio, mocker):
    stale = Audio.objects.get(pk=audio.pk)
    newer_data = {"editor": "kept", "size": {}, "size_file_names": {}}

    def editor_saves_during_probe(name):
        Audio.objects.filter(pk=audio.pk).update(title="edited title", data=newer_data)
        return 123

    mocker.patch.object(stale.m4a.storage, "size", side_effect=editor_saves_during_probe)

    cache_file_sizes(None, None, [stale])

    current = Audio.objects.get(pk=audio.pk)
    assert current.title == "edited title"
    assert current.data == {"editor": "kept", "size": {"m4a": 123}, "size_file_names": {"m4a": audio.m4a.name}}
    assert stale.data == current.data


def test_audio_model_admin_uses_derivation_service(mocker, audio):
    save_audio = mocker.patch("cast.admin.save_audio_with_derivations")
    audio_admin = AudioAdmin(Audio, None)

    audio_admin.save_model(None, audio, None, False)

    save_audio.assert_called_once_with(audio)


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
        short_bio="bio" * 10_000,
        transcript_variants="private" * 10_000,
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

    with CaptureQueriesContext(connection) as queries:
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

    selects = [query["sql"] for query in queries if 'FROM "cast_contributor' in query["sql"]]
    assert len(selects) == 2
    contributor_sql, link_sql = selects
    assert '"display_name"' in contributor_sql and '"default_role"' in contributor_sql
    assert '"service"' in link_sql
    assert '"cast_contributor".' not in link_sql and '"url"' not in link_sql
    assert all('"short_bio"' not in sql and '"transcript_variants"' not in sql for sql in selects)


@pytest.mark.django_db(databases=["default", "migration_other"])
def test_contributor_link_options_use_contributor_read_alias(admin_client, settings):
    class SplitRouter:
        def db_for_read(self, model, **hints):
            if model is Contributor:
                return "migration_other"
            if model is ContributorLink:
                return "default"
            return None

        def allow_relation(self, left, right, **hints):
            if isinstance(left, (Contributor, ContributorLink)) and isinstance(right, (Contributor, ContributorLink)):
                return True
            return None

    primary = Contributor.objects.create(display_name="Primary guest", slug="guest")
    ContributorLink.objects.create(
        pk=101, contributor=primary, service=ContributorLink.SERVICE_YOUTUBE, url="https://example.com/video"
    )
    replica = Contributor.objects.using("migration_other").create(
        pk=primary.pk, display_name="Replica host", slug="guest", default_role=EpisodeContributor.ROLE_HOST
    )
    link = ContributorLink.objects.using("migration_other").create(
        pk=102, contributor=replica, service=ContributorLink.SERVICE_WEBSITE, url="https://example.com/host"
    )
    settings.DATABASE_ROUTERS = [SplitRouter()]

    response = admin_client.get(reverse("cast-contributors:links"), {"contributor_id": replica.pk})

    assert response.status_code == 200
    assert response.json() == {
        "defaultLinkId": str(link.pk),
        "defaultRole": EpisodeContributor.ROLE_HOST,
        "links": [{"contributorId": str(replica.pk), "text": "Replica host: Website", "value": str(link.pk)}],
    }


@pytest.mark.django_db
@pytest.mark.parametrize("contributor_id", ["invalid", -1])
def test_contributor_link_options_with_invalid_or_missing_contributor_id(admin_client, contributor_id):
    response = admin_client.get(reverse("cast-contributors:links"), {"contributor_id": contributor_id})

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


@pytest.mark.django_db
@pytest.mark.parametrize("performance", [{}, {"ham": {"precision": 1, "recall": 1, "f1": 1}}])
def test_name_only_filter_admin_views_are_safe(admin_client, performance, settings):
    settings.ROOT_URLCONF = "tests.spamfilter_admin_urls"
    spamfilter = SpamFilter.objects.create(name="not trained", performance=performance)
    for url in (
        reverse("admin:cast_spamfilter_change", args=[spamfilter.pk]),
        reverse("admin:cast_spamfilter_changelist"),
    ):
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "Not trained" in response.content.decode()


def test_admin_missing_class_metrics_are_explicit():
    admin = SpamfilterModelAdmin(SpamFilter, None)
    assert admin.spam(SpamFilter()) == "Not trained / no metrics"
    assert admin.ham(SpamFilter()) == "Not trained / no metrics"
    assert admin.ham(SpamFilter(performance={"ham": {"bad": "diagnostic"}})) == {"bad": "diagnostic"}


@pytest.mark.django_db
def test_admin_retrain_reports_small_corpus(admin_client, settings, monkeypatch):
    settings.ROOT_URLCONF = "tests.spamfilter_admin_urls"
    spamfilter = SpamFilter.objects.create(name="too small")
    monkeypatch.setattr(SpamFilter, "get_training_data_comments", classmethod(lambda cls: [("ham", "one")]))
    response = admin_client.post(
        reverse("admin:cast_spamfilter_changelist"),
        {"action": "retrain", "_selected_action": [spamfilter.pk]},
        follow=True,
    )
    assert response.status_code == 200
    from django.contrib.messages import get_messages

    assert "corpus must contain at least one message per fold" in [
        str(message) for message in get_messages(response.wsgi_request)
    ]
    spamfilter.refresh_from_db()
    assert spamfilter.model == {}
    assert spamfilter.performance == {}
