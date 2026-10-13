import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from cast.models import TemplateBaseDirectory
from cast.models.repository import FeedContext


@pytest.mark.django_db
@pytest.mark.parametrize("repository", ["cached", "models"])
@pytest.mark.parametrize("blog_theme", ["plain", None])
@pytest.mark.parametrize("route", ["latest_entries_feed", "latest_entries_atom_feed"])
def test_shared_feed_uses_default_theme(client, post, blog, site, settings, repository, blog_theme, route):
    settings.CAST_REPOSITORY = "default" if repository == "cached" else "models"
    blog.template_base_dir = blog_theme
    blog.save()
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "plain"})
    session = client.session
    session["template_base_dir"] = "bootstrap4"
    session.save()
    url = reverse(f"cast:{route}", kwargs={"slug": blog.slug})
    cache.clear()
    response = client.get(url, {"theme": "bootstrap4"})
    assert response.status_code == 200
    names = [template.name for template in response.templates]
    assert "cast/plain/post_body.html" in names
    assert "cast/bootstrap4/post_body.html" not in names
    assert Client().get(url, {"theme": "bootstrap4"}).content == response.content
    cache.clear()
    assert Client().get(url).content == response.content


@pytest.mark.django_db
def test_cached_feed_context_ignores_internal_theme_override(rf, post, blog):
    blog.template_base_dir = "plain"
    blog.save()
    request = rf.get("/", {"template_base_dir": "bootstrap4"})
    request.session = {"template_base_dir": "bootstrap4"}
    request.cast_template_base_dir = "bootstrap4"
    data = FeedContext.data_for_feed_cachable(request=request, blog=blog)
    assert data["template_base_dir"] == "plain"
