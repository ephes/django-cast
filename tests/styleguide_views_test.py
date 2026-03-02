import pytest
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import Http404
from django.urls import reverse

from cast.models import Blog, Podcast, Post, TemplateBaseDirectory
from cast.views import styleguide as styleguide_view
from cast.views.styleguide import STYLEGUIDE_BLOG_SLUG, STYLEGUIDE_PODCAST_SLUG


@pytest.mark.django_db
def test_styleguide_disabled_returns_404(settings, client):
    settings.CAST_ENABLE_STYLEGUIDE = False
    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_enabled_renders_and_is_idempotent(settings, client, site):
    settings.CAST_ENABLE_STYLEGUIDE = True
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "plain"})

    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 200
    assert response.context["styleguide_active_theme"] == "plain"
    styleguide_audio = response.context["styleguide_audio"]
    assert styleguide_audio is not None
    assert styleguide_audio.transcript.podlove is not None

    expected_posts = max(12, getattr(settings, "POST_LIST_PAGINATION", 5) + 1)
    assert Blog.objects.filter(slug="styleguide-blog").count() == 1
    assert Post.objects.filter(slug__startswith="styleguide-post").count() == expected_posts

    response_second = client.get(reverse("cast:styleguide"))
    assert response_second.status_code == 200
    assert Blog.objects.filter(slug="styleguide-blog").count() == 1
    assert Post.objects.filter(slug__startswith="styleguide-post").count() == expected_posts


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_vue_theme_builds_payload(settings, rf, site, monkeypatch):
    settings.CAST_ENABLE_STYLEGUIDE = True
    settings.CAST_CUSTOM_THEMES = [("vue", "Vue")]
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "plain"})

    captured = {}

    def fake_render(_request, _template, context):
        captured["context"] = context
        return styleguide_view.HttpResponse("ok")

    monkeypatch.setattr(styleguide_view, "render", fake_render)

    request = rf.get(f"{reverse('cast:styleguide')}?theme=vue")
    response = styleguide_view.styleguide(request)
    assert response.status_code == 200
    assert captured["context"]["styleguide_active_theme"] == "vue"
    payload = captured["context"]["styleguide_vue_payload"]
    assert payload["active_theme"] == "vue"
    assert payload["media_post_slug"]


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_seeds_comments_for_media_post(settings, client, site, comments_enabled):
    settings.CAST_ENABLE_STYLEGUIDE = True
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "plain"})

    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 200

    from django.contrib.auth import get_user_model
    from django_comments import get_model as get_comment_model

    media_post = response.context["styleguide_media_post"]
    comment_model = get_comment_model()
    assert comment_model.objects.for_model(media_post).count() >= 2

    styleguide_user = get_user_model().objects.get(username=styleguide_view.STYLEGUIDE_USER_NAME)
    comments = (
        comment_model.objects.for_model(media_post).filter(user=styleguide_user).order_by("submit_date", "pk").all()
    )
    assert len(comments) >= 2
    comments[0].comment = "Old comment"
    comments[0].save(update_fields=["comment"])
    comments[1].comment = "Old reply"
    comments[1].save(update_fields=["comment"])

    response_second = client.get(reverse("cast:styleguide"))
    assert response_second.status_code == 200

    refreshed = (
        comment_model.objects.for_model(media_post).filter(user=styleguide_user).order_by("submit_date", "pk").all()
    )
    assert "intentionally longer" in refreshed[0].comment
    assert "Threaded reply to show hierarchy" in refreshed[1].comment


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_theme_switch_does_not_persist_session(settings, client, site):
    settings.CAST_ENABLE_STYLEGUIDE = True
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "bootstrap4"})

    response = client.get(f"{reverse('cast:styleguide')}?theme=plain")
    assert response.status_code == 200
    assert response.context["styleguide_active_theme"] == "plain"
    assert "template_base_dir" not in client.session


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_uses_session_theme(settings, client, site):
    settings.CAST_ENABLE_STYLEGUIDE = True
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "bootstrap4"})

    session = client.session
    session["template_base_dir"] = "plain"
    session.save()

    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 200
    assert response.context["styleguide_active_theme"] == "plain"


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_invalid_theme_uses_current(settings, client, site):
    settings.CAST_ENABLE_STYLEGUIDE = True
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "bootstrap4"})

    response = client.get(f"{reverse('cast:styleguide')}?theme=not-a-theme")
    assert response.status_code == 200
    assert response.context["styleguide_active_theme"] == "bootstrap4"


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_missing_templates_fallback_warning(settings, client, site):
    settings.CAST_ENABLE_STYLEGUIDE = True
    settings.CAST_CUSTOM_THEMES = [("custom_theme", "Custom Theme")]
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "bootstrap4"})

    response = client.get(f"{reverse('cast:styleguide')}?theme=custom_theme")
    assert response.status_code == 200
    assert response.context["styleguide_active_theme"] == "bootstrap4"
    warning = response.context["styleguide_warning"]
    assert warning is not None
    assert "custom_theme" in warning


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_creates_site_when_missing(settings, client):
    settings.CAST_ENABLE_STYLEGUIDE = True
    from wagtail.models import Site

    Site.objects.all().delete()

    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 200
    assert Site.objects.exists()


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_repairs_episode_audio(settings, client, site):
    settings.CAST_ENABLE_STYLEGUIDE = True
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "bootstrap4"})

    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 200

    from cast.models import Episode

    episode = Episode.objects.filter(slug="styleguide-episode-1").first()
    assert episode is not None
    episode.podcast_audio = None
    episode.save()

    response_second = client.get(reverse("cast:styleguide"))
    assert response_second.status_code == 200

    episode.refresh_from_db()
    assert episode.podcast_audio is not None


@pytest.mark.django_db
def test_styleguide_current_site_theme_prefers_session(rf):
    request = rf.get("/styleguide/")
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session["template_base_dir"] = "plain"
    request.session.save()

    theme = styleguide_view._current_site_theme(request, {"bootstrap4", "plain"})
    assert theme == "plain"


@pytest.mark.django_db
def test_styleguide_current_site_theme_ignores_invalid_session(rf, site):
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "plain"})
    request = rf.get("/styleguide/")
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session["template_base_dir"] = "invalid"
    request.session.save()

    theme = styleguide_view._current_site_theme(request, {"bootstrap4", "plain"})
    assert theme == "plain"


@pytest.mark.django_db
def test_styleguide_current_site_theme_without_session_uses_site_setting(rf, site):
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "plain"})
    request = rf.get("/styleguide/")

    theme = styleguide_view._current_site_theme(request, {"bootstrap4", "plain"})
    assert theme == "plain"


def test_styleguide_find_fallback_theme_prefers_bootstrap5(monkeypatch):
    def fake_exists(theme_slug):
        return theme_slug in {"bootstrap5", "bootstrap4"}

    monkeypatch.setattr(styleguide_view, "_styleguide_template_exists", fake_exists)
    assert styleguide_view._find_fallback_theme({"bootstrap5", "bootstrap4", "plain"}) == "bootstrap5"


def test_styleguide_find_fallback_theme_prefers_defaults(monkeypatch):
    def fake_exists(theme_slug):
        return theme_slug == "bootstrap4"

    monkeypatch.setattr(styleguide_view, "_styleguide_template_exists", fake_exists)
    assert styleguide_view._find_fallback_theme({"bootstrap4", "plain"}) == "bootstrap4"


def test_styleguide_find_fallback_theme_uses_available(monkeypatch):
    def fake_exists(theme_slug):
        return theme_slug == "custom"

    monkeypatch.setattr(styleguide_view, "_styleguide_template_exists", fake_exists)
    assert styleguide_view._find_fallback_theme({"custom"}) == "custom"


def test_styleguide_find_fallback_theme_raises_without_templates(monkeypatch):
    monkeypatch.setattr(styleguide_view, "_styleguide_template_exists", lambda _slug: False)
    with pytest.raises(Http404):
        styleguide_view._find_fallback_theme({"custom"})


def test_styleguide_warns_when_requested_theme_missing(monkeypatch, rf):
    def fake_exists(theme_slug):
        return theme_slug == "bootstrap4"

    monkeypatch.setattr(styleguide_view, "_styleguide_template_exists", fake_exists)

    request = rf.get("/styleguide/?theme=plain")
    theme = styleguide_view._resolve_styleguide_theme(request)

    assert theme.active == "bootstrap4"
    assert theme.warning is not None


def test_styleguide_missing_templates_without_warning(monkeypatch, rf):
    calls = {"count": 0}

    def fake_exists(theme_slug):
        calls["count"] += 1
        if calls["count"] == 1:
            return False
        return theme_slug == "bootstrap4"

    monkeypatch.setattr(styleguide_view, "_styleguide_template_exists", fake_exists)

    request = rf.get("/styleguide/?theme=bootstrap4")
    theme = styleguide_view._resolve_styleguide_theme(request)

    assert theme.active == "bootstrap4"
    assert theme.warning is None


def test_styleguide_extract_cover_image_url():
    html = '<meta property="og:image" content="/media/cover.jpg">'
    url = styleguide_view._extract_cover_image_url(html, "https://example.com/show/episode/")
    assert url == "https://example.com/media/cover.jpg"


def test_styleguide_extract_transcript_data_from_section():
    html = """
    <section class="transcript-segment">
      <p class="transcript-meta"><time>00:00:01.000</time></p>
      <p class="transcript-text">Hello world</p>
    </section>
    """
    data = styleguide_view._extract_transcript_data(html)
    assert data is not None
    assert data["transcripts"][0]["text"] == "Hello world"


def test_styleguide_extract_podlove_player_api_url():
    html = '<podlove-player data-url="/api/audios/podlove/82/post/140/"></podlove-player>'
    url = styleguide_view._extract_podlove_player_api_url(html, "https://python-podcast.de/show/data-science/")
    assert url == "https://python-podcast.de/api/audios/podlove/82/post/140/"


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_resets_invalid_blog_theme_and_repulishes(settings, client, site, user):
    settings.CAST_ENABLE_STYLEGUIDE = True
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "bootstrap4"})
    existing_blog = Blog.objects.filter(slug=STYLEGUIDE_BLOG_SLUG).first()
    if existing_blog is not None:
        existing_blog.delete()

    blog = Blog(
        title="Styleguide Blog",
        slug=STYLEGUIDE_BLOG_SLUG,
        owner=user,
        template_base_dir=styleguide_view._styleguide_default_theme(),
    )
    site.root_page.add_child(instance=blog)
    Blog.objects.filter(pk=blog.pk).update(template_base_dir="invalid")
    blog.refresh_from_db()
    blog.unpublish()

    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 200

    blog.refresh_from_db()
    assert blog.template_base_dir == styleguide_view._styleguide_default_theme()
    assert blog.live is True


@pytest.mark.django_db
@pytest.mark.slow
def test_styleguide_resets_invalid_podcast_theme(settings, client, site, user):
    settings.CAST_ENABLE_STYLEGUIDE = True
    TemplateBaseDirectory.objects.update_or_create(site=site, defaults={"name": "bootstrap4"})
    existing_podcast = Podcast.objects.filter(slug=STYLEGUIDE_PODCAST_SLUG).first()
    if existing_podcast is not None:
        existing_podcast.delete()

    podcast = Podcast(
        title="Styleguide Podcast",
        slug=STYLEGUIDE_PODCAST_SLUG,
        owner=user,
        template_base_dir=styleguide_view._styleguide_default_theme(),
    )
    site.root_page.add_child(instance=podcast)
    Podcast.objects.filter(pk=podcast.pk).update(template_base_dir="invalid")

    response = client.get(reverse("cast:styleguide"))
    assert response.status_code == 200

    podcast.refresh_from_db()
    assert podcast.template_base_dir == styleguide_view._styleguide_default_theme()
