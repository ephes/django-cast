"""Current link ownership at the database write boundary."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection

from cast.models import Contributor, ContributorLink, Episode, EpisodeContributor


@pytest.mark.django_db
def test_assignment_rechecks_cached_link(episode):
    owner = Contributor.objects.create(display_name="Synthetic A", slug="a")
    other = Contributor.objects.create(display_name="Synthetic B", slug="b")
    link = ContributorLink.objects.create(contributor=owner, url="https://example.com/a")
    assignment = EpisodeContributor(episode=episode, contributor=owner, link=link)
    ContributorLink.objects.filter(pk=link.pk).update(contributor=other)
    with pytest.raises(ValidationError):
        assignment.save()


@pytest.fixture
def race_episode(transactional_db):
    if connection.vendor != "postgresql":
        pytest.skip("requires independent PostgreSQL row locks")
    return Episode.add_root(title="Synthetic episode", slug="synthetic-episode")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("first", ["link", "assignment"])
@pytest.mark.parametrize("existing", [False, True])
def test_postgres_link_owner_and_assignment_serialize(race_episode, monkeypatch, first, existing):
    episode = race_episode
    owner = Contributor.objects.create(display_name="Synthetic A", slug="a")
    other = Contributor.objects.create(display_name="Synthetic B", slug="b")
    link = ContributorLink.objects.create(contributor=owner, url="https://example.com/a")
    assignment = EpisodeContributor(episode=episode, contributor=owner)
    if existing:
        assignment.save()
    assignment.link = ContributorLink.objects.get(pk=link.pk)
    link.contributor = other
    paused = threading.Event()
    release = threading.Event()
    started = threading.Event()
    done = threading.Event()
    model, method = (
        (ContributorLink, "_validate_episode_assignments_match_contributor")
        if first == "link"
        else (EpisodeContributor, "clean")
    )
    original = getattr(model, method)

    def pause(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if threading.current_thread().name.endswith("_0"):
            paused.set()
            assert release.wait(10)

    monkeypatch.setattr(model, method, pause)

    def save(obj, second=False):
        close_old_connections()
        try:
            if second:
                started.set()
            try:
                obj.save()
            except ValidationError:
                return False
            return True
        finally:
            if second:
                done.set()
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(save, link if first == "link" else assignment)
        try:
            assert paused.wait(10)
            b = pool.submit(save, assignment if first == "link" else link, True)
            assert started.wait(10)
            done.wait(0.3)
        finally:
            release.set()
        results = [a.result(timeout=20), b.result(timeout=20)]
    assert results == [True, False]
    for row in EpisodeContributor.objects.filter(link_id=link.pk).select_related("link"):
        assert row.contributor_id == row.link.contributor_id
