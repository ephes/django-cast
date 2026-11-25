"""The view and command reserve one database writer before absent-root reads."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection
from wagtail.models import Site

from cast.models import Blog, Episode, Podcast
from cast.views import styleguide as view


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("command", [False, True])
def test_seed_serializes_absent_roots(monkeypatch, command, site):
    assets = view._prepare_styleguide_assets()
    first_read, second_started, second_read, release = (threading.Event() for _ in range(4))
    original = view._ensure_blog
    connections = []

    def ensure_blog(*args):
        if threading.current_thread().name.endswith("_0"):
            first_read.set()
            assert release.wait(10)
        else:
            second_read.set()
        return original(*args)

    monkeypatch.setattr(view, "_ensure_blog", ensure_blog)
    monkeypatch.setattr("cast.management.commands.ensure_reference_site._prepare_styleguide_assets", lambda: assets)
    monkeypatch.setattr("cast.management.commands.ensure_reference_site._styleguide_context", lambda *a, **kw: {})

    def seed(second=False):
        close_old_connections()
        try:
            connection.ensure_connection()
            connections.append(connection.connection)
            if second:
                second_started.set()
            if second and command:
                call_command("ensure_reference_site", verbosity=0)
            else:
                view._ensure_styleguide_seed_data(assets=assets)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(seed)
        try:
            assert first_read.wait(10)
            second = pool.submit(seed, True)
            assert second_started.wait(10)
            premature_read = second_read.wait(0.3)
        finally:
            release.set()
        first.result(timeout=30)
        second.result(timeout=30)
    assert connections[0] is not connections[1]
    assert not premature_read
    site = Site.objects.first()
    assert Blog.objects.child_of(site.root_page).filter(slug=view.STYLEGUIDE_BLOG_SLUG).count() == 1
    assert Podcast.objects.child_of(site.root_page).filter(slug=view.STYLEGUIDE_PODCAST_SLUG).count() == 1
    assert Episode.objects.filter(slug=view.STYLEGUIDE_EPISODE_SLUG).count() == 1
