"""Defaults for a new episode and Wagtail's built-in slug synchronization."""

import pytest
from django.urls import reverse

from cast.models import Contributor, Episode, EpisodeContributor
from cast.models.pages import CustomEpisodeForm

pytestmark = pytest.mark.django_db


class MinimalEpisodeForm(CustomEpisodeForm):
    class Meta:
        model = Episode
        fields = ()


def test_new_episode_prefills_only_latest_hosts_in_order(podcast, episode):
    hosts = [Contributor.objects.create(display_name=name, slug=name.lower()) for name in ("First", "Second")]
    guest = Contributor.objects.create(display_name="Guest", slug="guest")
    for index, contributor in enumerate(hosts):
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role="host", sort_order=index)
    EpisodeContributor.objects.create(episode=episode, contributor=guest, role="guest", sort_order=2)
    episode.save_revision()
    instance = Episode(title="New")
    form = MinimalEpisodeForm(instance=instance, parent_page=podcast)
    assert [row.contributor for row in form.instance.contributor_assignments.all()] == hosts
    assert all(row.pk is None for row in form.instance.contributor_assignments.all())
    existing = Episode(title="Custom")
    existing.contributor_assignments.add(EpisodeContributor(contributor=guest))
    assert [
        row.contributor
        for row in MinimalEpisodeForm(instance=existing, parent_page=podcast).instance.contributor_assignments.all()
    ] == [guest]
    assert not MinimalEpisodeForm({}, instance=Episode(), parent_page=podcast).instance.contributor_assignments.all()
    assert not MinimalEpisodeForm(instance=Episode()).instance.contributor_assignments.all()


@pytest.mark.parametrize("order,roles", [("guests_first", ["guest", "host"]), ("hosts_first", ["host", "guest"])])
def test_podcast_controls_new_episode_contributor_order(podcast, order, roles):
    podcast.contributor_order = order
    podcast.save()
    instance = Episode(title="New", slug="new")
    for role in ("host", "guest"):
        person = Contributor.objects.create(display_name=role, slug=role)
        instance.contributor_assignments.add(EpisodeContributor(contributor=person, role=role))
    form = MinimalEpisodeForm({}, instance=instance, parent_page=podcast)
    assert form.is_valid(), form.errors
    result = form.save(commit=False)
    assert [row.role for row in result.contributor_assignments.all()] == roles


def test_contributor_uses_wagtail_slug_sync(admin_client):
    content = admin_client.get(reverse("wagtailsnippets_cast_contributor:add")).content.decode()
    assert "w-sync" in content
    assert 'data-w-sync-target-value="#id_slug"' in content


def test_episode_form_save_persists_when_requested(podcast):
    from unittest.mock import patch

    instance = Episode(title="New", slug="new")
    form = MinimalEpisodeForm({}, instance=instance, parent_page=podcast)
    assert form.is_valid()
    with patch.object(Episode, "save") as save:
        assert form.save() is instance
    save.assert_called_once()


def test_new_episode_prefill_skips_newer_episode_without_hosts(podcast, episode):
    from datetime import timedelta

    host = Contributor.objects.create(display_name="Host", slug="host")
    EpisodeContributor.objects.create(episode=episode, contributor=host, role="host")
    episode.save_revision()
    special = Episode(title="Special", slug="special", visible_date=episode.visible_date + timedelta(days=1))
    podcast.add_child(instance=special)
    form = MinimalEpisodeForm(instance=Episode(title="New"), parent_page=podcast)
    assert [row.contributor for row in form.instance.contributor_assignments.all()] == [host]


def test_new_episode_prefill_stays_empty_without_any_hosts(podcast, episode):
    form = MinimalEpisodeForm(instance=Episode(title="New"), parent_page=podcast)
    assert not form.instance.contributor_assignments.all()
