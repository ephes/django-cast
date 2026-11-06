import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from cast.models import Contributor, ContributorLink, Episode, EpisodeContributor
from cast.transcripts.editing import episode_from_latest_revision
from cast.voxhelm import count_episode_diarization_speakers
from tests.factories import UserFactory


@pytest.fixture
def hosts(db):
    return [
        Contributor.objects.create(display_name="Jochen", slug="jochen", default_role="host"),
        Contributor.objects.create(display_name="Dominik", slug="dominik", default_role="host"),
        Contributor.objects.create(display_name="Hidden Guest", slug="hidden-guest", visible=False),
    ]


def create_payload(podcast, **overrides):
    payload = {
        "parent": {"id": podcast.id},
        "title": "Episode with hosts",
        "slug": "episode-with-hosts",
        "overview": [{"type": "paragraph", "value": "<p>Notes</p>"}],
    }
    payload.update(overrides)
    return payload


class TestContributorList:
    pytestmark = pytest.mark.django_db

    def test_lists_and_filters_contributors(self, api_client, admin_user, hosts):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_contributors")

        response = api_client.get(url)
        assert response.status_code == 200
        results = response.json()["results"]
        assert [item["slug"] for item in results] == ["dominik", "hidden-guest", "jochen"]
        assert results[2] == {
            "id": hosts[0].pk,
            "slug": "jochen",
            "display_name": "Jochen",
            "default_role": "host",
            "visible": True,
        }

        by_query = api_client.get(f"{url}?q=dom")
        assert [item["slug"] for item in by_query.json()["results"]] == ["dominik"]

        by_slug = api_client.get(f"{url}?slug=jochen&slug=hidden-guest")
        assert [item["slug"] for item in by_slug.json()["results"]] == ["hidden-guest", "jochen"]

        unsupported = api_client.get(f"{url}?role=host")
        assert unsupported.status_code == 400
        assert unsupported.json()["errors"]["role"][0]["code"] == "unsupported_parameter"

    def test_requires_wagtail_admin_access(self, api_client):
        user = UserFactory(is_staff=True)
        api_client.force_authenticate(user=user)
        response = api_client.get(reverse("cast:api:editor_contributors"))
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

        user.user_permissions.add(
            Permission.objects.get(codename="access_admin", content_type__app_label="wagtailadmin")
        )
        api_client.force_authenticate(user=type(user).objects.get(pk=user.pk))
        assert api_client.get(reverse("cast:api:editor_contributors")).status_code == 200


class TestEpisodeContributors:
    pytestmark = pytest.mark.django_db

    def test_create_assigns_ordered_contributors_by_slug_and_id(self, api_client, admin_user, podcast, hosts):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(
            reverse("cast:api:editor_episode_create"),
            create_payload(
                podcast,
                contributors=[{"slug": "dominik"}, {"id": hosts[0].pk, "role": "host"}, {"slug": "hidden-guest"}],
            ),
            format="json",
        )

        assert response.status_code == 201, response.content
        assert response.json()["contributors"] == [
            {"id": hosts[1].pk, "slug": "dominik", "display_name": "Dominik", "role": "host", "visible": True},
            {"id": hosts[0].pk, "slug": "jochen", "display_name": "Jochen", "role": "host", "visible": True},
            {
                "id": hosts[2].pk,
                "slug": "hidden-guest",
                "display_name": "Hidden Guest",
                "role": "guest",
                "visible": False,
            },
        ]
        episode = Episode.objects.get(pk=response.json()["id"])
        assert list(episode.contributor_assignments.values_list("contributor__slug", flat=True)) == [
            "dominik",
            "jochen",
            "hidden-guest",
        ]
        draft = episode_from_latest_revision(episode)
        assert count_episode_diarization_speakers(draft) == 3

        detail = api_client.get(reverse("cast:api:editor_episode_detail", kwargs={"pk": episode.pk}))
        assert [item["slug"] for item in detail.json()["contributors"]] == ["dominik", "jochen", "hidden-guest"]

    def test_episode_without_contributors_returns_empty_list(self, api_client, admin_user, podcast):
        api_client.force_authenticate(user=admin_user)
        response = api_client.post(reverse("cast:api:editor_episode_create"), create_payload(podcast), format="json")
        assert response.status_code == 201
        assert response.json()["contributors"] == []

    def test_patch_replaces_contributors_on_the_draft_revision_and_keeps_links(
        self, api_client, admin_user, podcast, hosts
    ):
        api_client.force_authenticate(user=admin_user)
        created = api_client.post(
            reverse("cast:api:editor_episode_create"),
            create_payload(podcast, contributors=[{"slug": "jochen"}, {"slug": "dominik"}]),
            format="json",
        ).json()
        link = ContributorLink.objects.create(contributor=hosts[0], url="https://example.com/jochen")
        episode = Episode.objects.get(pk=created["id"])
        draft = episode_from_latest_revision(episode)
        for assignment in draft.contributor_assignments.all():
            if assignment.contributor_id == hosts[0].pk:
                assignment.link = link
        revision = draft.save_revision(user=admin_user)

        response = api_client.patch(
            reverse("cast:api:editor_episode_detail", kwargs={"pk": episode.pk}),
            {
                "base_revision_id": revision.pk,
                "contributors": [{"slug": "hidden-guest", "role": "guest"}, {"slug": "jochen"}],
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert [(item["slug"], item["role"]) for item in response.json()["contributors"]] == [
            ("hidden-guest", "guest"),
            ("jochen", "host"),
        ]
        latest = episode_from_latest_revision(Episode.objects.get(pk=episode.pk))
        assignments = sorted(latest.contributor_assignments.all(), key=lambda assignment: assignment.sort_order)
        assert [assignment.contributor_id for assignment in assignments] == [hosts[2].pk, hosts[0].pk]
        assert assignments[1].link_id == link.pk

        cleared = api_client.patch(
            reverse("cast:api:editor_episode_detail", kwargs={"pk": episode.pk}),
            {"base_revision_id": response.json()["latest_revision_id"], "contributors": []},
            format="json",
        )
        assert cleared.status_code == 200
        assert cleared.json()["contributors"] == []

    def test_contributor_validation_errors(self, api_client, admin_user, podcast, hosts):
        api_client.force_authenticate(user=admin_user)
        url = reverse("cast:api:editor_episode_create")

        unknown = api_client.post(
            url,
            create_payload(podcast, contributors=[{"slug": "jochen"}, {"slug": "nobody"}, {"id": 999999}]),
            format="json",
        )
        assert unknown.status_code == 400
        errors = unknown.json()["errors"]
        assert errors["contributors.1.slug"][0]["code"] == "not_found"
        assert errors["contributors.2.id"][0]["code"] == "not_found"

        duplicate = api_client.post(
            url,
            create_payload(podcast, contributors=[{"slug": "jochen"}, {"id": hosts[0].pk, "role": "host"}]),
            format="json",
        )
        assert duplicate.status_code == 400
        assert duplicate.json()["errors"]["contributors.1"][0]["code"] == "duplicate"

        both = api_client.post(
            url, create_payload(podcast, contributors=[{"slug": "jochen", "id": hosts[0].pk}]), format="json"
        )
        assert both.status_code == 400
        assert "contributors.0.non_field_errors" in both.json()["errors"]

        bad_role = api_client.post(
            url, create_payload(podcast, contributors=[{"slug": "jochen", "role": "editor"}]), format="json"
        )
        assert bad_role.status_code == 400
        assert bad_role.json()["errors"]["contributors.0.role"][0]["code"] == "invalid_choice"
        assert not Episode.objects.filter(slug="episode-with-hosts").exists()
        assert not EpisodeContributor.objects.exists()
