import json
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.sessions.models import Session
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from wagtail.images.models import Rendition
from wagtail.models import PageLogEntry, Revision

from cast.models import Gallery, Post
from cast.preview import render_editor_preview
from cast.preview_media import PreviewMedia, _media_id


@pytest.mark.parametrize("value, expected", [(None, None), ({"value": 4}, 4), ({}, None), (5, 5)])
def test_preview_media_id(value, expected):
    assert _media_id(value) == expected


def test_preview_media_id_accepts_model_instance():
    assert _media_id(SimpleNamespace(pk=3)) == 3


@pytest.mark.django_db
def test_preview_media_ignores_empty_and_missing_choosers(post):
    post.body = [
        {
            "type": "overview",
            "value": [
                {"type": "image", "value": None},
                {"type": "image", "value": 999999},
                {"type": "gallery", "value": {"layout": "default", "gallery": [None, {"value": None}]}},
            ],
        }
    ]
    media = PreviewMedia.from_post(post)
    assert media.images == media.audios == media.videos == media.renditions == {}


@pytest.mark.django_db
@pytest.mark.parametrize("captioned", [False, True])
def test_preview_renders_draft_media_without_content_writes(
    rf, post_with_image, image, audio, video, settings, captioned
):
    from cast.devdata import create_image

    # Rolled-back tests reuse image IDs, but Wagtail's rendition cache outlives
    # those transactions. Isolate it while testing persisted rendition rows.
    settings.CACHES = {**settings.CACHES, "renditions": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
    draft_image = create_image()
    # Initialize Wagtail's site settings before measuring rendering writes.
    post_with_image.get_template_base_dir(rf.get("/"))
    draft = post_with_image.get_latest_revision_as_object()
    draft.body = [
        {
            "type": "overview",
            "value": [
                {"type": "image", "value": draft_image.pk},
                {"type": "audio", "value": audio.pk},
                {"type": "video", "value": video.pk},
                {
                    "type": "gallery",
                    "value": {
                        "layout": "default",
                        "gallery": [
                            {"type": "item", "value": draft_image.pk},
                            {
                                "type": "item",
                                "value": {"image": image.pk, "caption": "Gallery-only preview image"}
                                if captioned
                                else image.pk,
                            },
                        ],
                    },
                },
            ],
        }
    ]
    before = (Gallery.objects.count(), Revision.objects.count(), PageLogEntry.objects.count())
    original_body = list(Post.objects.get(pk=draft.pk).body.raw_data)
    unrelated = image.get_rendition("width-400")
    for iteration in range(2):
        with CaptureQueriesContext(connection) as queries:
            response = draft.serve_preview(rf.get("/"), "")
            response.render()
        writes = [q["sql"] for q in queries if q["sql"].split()[0] in {"INSERT", "UPDATE", "DELETE"}]
        assert all('"wagtailimages_rendition"' in sql for sql in writes), writes
        if iteration:
            assert writes == []
        repository = response.context_data["repository"]
        assert set(repository.image_by_id) == {image.pk, draft_image.pk}
        assert set(repository.audio_by_id) == {audio.pk}
        assert set(repository.video_by_id) == {video.pk}
        assert repository.has_audio
        assert response.status_code == 200
        assert response["Cache-Control"] == "private, no-store"
        html = response.content.decode()
        assert any(rendition.url in html for rendition in repository.renditions_for_posts[draft_image.pk])
        assert 'class="cast-gallery-thumbnail"' in html
        assert ("<figcaption>Gallery-only preview image</figcaption>" in html) is captioned
        assert f'id="audio_{audio.pk}"' in html
        assert video.original.url in html
    assert before == (Gallery.objects.count(), Revision.objects.count(), PageLogEntry.objects.count())
    assert list(Post.objects.get(pk=draft.pk).body.raw_data) == original_body
    assert list(post_with_image.images.all()) == [image]
    assert not post_with_image.audios.exists()
    assert not post_with_image.videos.exists()
    assert not post_with_image.galleries.exists()
    assert Rendition.objects.filter(image=draft_image).exists()
    assert Rendition.objects.filter(pk=unrelated.pk).exists()


@pytest.mark.django_db
def test_unsaved_admin_preview_uses_body_without_creating_page(rf, blog, image, body_with_image):
    page = Post(title="Unsaved draft", slug="unsaved-draft", body=body_with_image)
    page._blog = blog
    before = Post.objects.count()
    response = page.serve_preview(rf.get("/"), "")
    response.render()
    assert image.pk in response.context_data["repository"].image_by_id
    assert Post.objects.count() == before
    assert page.pk is None


@pytest.mark.django_db
def test_removed_draft_audio_does_not_leave_player_enabled(rf, post_with_audio, body):
    post_with_audio.body = body
    response = post_with_audio.serve_preview(rf.get("/"), "")
    assert not response.context_data["repository"].has_audio
    assert response.context_data["repository"].audio_by_id == {}
    assert post_with_audio.audios.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("with_session", [False, True])
def test_api_preview_is_anonymous_and_does_not_inherit_theme(
    api_client, admin_user, user, post, mocker, rf, with_session
):
    api_client.force_authenticate(user=admin_user)
    if with_session:
        api_client.force_login(user)
        session = api_client.session
        session["template_base_dir"] = "plain"
        session.save()
    before_sessions = list(Session.objects.values())
    spy = mocker.spy(Post, "get_preview_context")
    url = reverse("cast:api:editor_post_preview", kwargs={"pk": post.pk})
    response = api_client.get(url, HTTP_AUTHORIZATION="Bearer deliberately-not-a-real-credential")
    assert response.status_code == 200
    rendered_request = spy.call_args.args[1]
    assert not rendered_request.user.is_authenticated
    assert "HTTP_COOKIE" not in rendered_request.META
    assert "HTTP_AUTHORIZATION" not in rendered_request.META
    assert not rendered_request.session.get("template_base_dir")
    assert response.context_data["template_base_dir"] == post.get_template_base_dir(rf.get("/"))
    assert list(Session.objects.values()) == before_sessions
    assert "no-store" in response["Cache-Control"]


@pytest.mark.django_db
def test_admin_preview_keeps_session_identity_and_theme(client, admin_user, post, mocker):
    client.force_login(admin_user)
    session = client.session
    session["template_base_dir"] = "plain"
    session.save()
    post.save_revision(user=admin_user)
    spy = mocker.spy(Post, "get_preview_context")
    response = client.get(reverse("wagtailadmin_pages:view_draft", args=[post.pk]))
    assert response.status_code == 200
    assert spy.call_args.args[1].user == admin_user
    assert response.context_data["template_base_dir"] == "plain"
    assert "no-store" in response["Cache-Control"]


@pytest.mark.django_db
def test_preview_cannot_reuse_or_replace_public_page_cache(settings, client, api_client, admin_user, post):
    # Do not leave cached pages for later tests which reuse the same URL/IDs.
    settings.CACHES = {
        **settings.CACHES,
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": uuid4().hex},
    }
    settings.MIDDLEWARE = [
        "django.middleware.cache.UpdateCacheMiddleware",
        *settings.MIDDLEWARE,
        "django.middleware.cache.FetchFromCacheMiddleware",
    ]
    post.body = json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "PUBLIC MARKER"}]}])
    post.save()
    live_url = post.get_url()
    assert b"PUBLIC MARKER" in client.get(live_url).content
    draft = post.get_latest_revision_as_object()
    draft.body = json.dumps([{"type": "overview", "value": [{"type": "paragraph", "value": "SECRET DRAFT"}]}])
    draft.save_revision(user=admin_user)
    api_client.force_authenticate(user=admin_user)
    response = api_client.get(reverse("cast:api:editor_post_preview", kwargs={"pk": post.pk}))
    assert response.status_code == 200
    assert b"SECRET DRAFT" in response.content
    assert b"PUBLIC MARKER" not in response.content
    assert "no-store" in response["Cache-Control"]
    public = client.get(live_url)
    assert b"PUBLIC MARKER" in public.content
    assert b"SECRET DRAFT" not in public.content


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", "theme=plain"])
def test_preview_cache_key_preserves_upstream_query(post, mocker, query):
    from wagtail.models.preview import PreviewableMixin

    mocker.patch.object(PreviewableMixin, "_get_dummy_headers", return_value={"QUERY_STRING": query})
    headers = post._get_dummy_headers()
    assert headers["QUERY_STRING"].startswith(f"{query}&_cast_preview=".lstrip("&"))


@pytest.mark.django_db
def test_editor_preview_passes_only_transport_metadata(rf, post, admin_user, mocker):
    request = rf.get(
        "/?theme=plain",
        secure=True,
        HTTP_COOKIE="sessionid=not-a-real-session",
        HTTP_AUTHORIZATION="Bearer not-a-real-credential",
        REMOTE_USER="someone",
        HTTP_X_FORWARDED_USER="someone",
        HTTP_X_FORWARDED_FOR="192.0.2.1",
        HTTP_USER_AGENT="test",
    )
    request.user = admin_user
    request.session = {"template_base_dir": "plain"}
    render = mocker.patch.object(post, "make_preview_request")
    render_editor_preview(post, request)
    original = render.call_args.kwargs["original_request"]
    assert not original.user.is_authenticated
    assert dict(original.session.items()) == {}
    assert original.session.session_key is None
    assert not original.COOKIES
    assert not original.GET
    assert original.scheme == "https"
    assert isinstance(original.META["wsgi.input"], BytesIO)
    assert original.META["HTTP_X_FORWARDED_FOR"] == "192.0.2.1"
    assert original.META["HTTP_USER_AGENT"] == "test"
    assert not {"REMOTE_USER", "HTTP_X_FORWARDED_USER", "HTTP_AUTHORIZATION", "HTTP_COOKIE"} & original.META.keys()
    assert request.user == admin_user
    assert request.session == {"template_base_dir": "plain"}
    assert request.META["HTTP_AUTHORIZATION"] == "Bearer not-a-real-credential"


@pytest.mark.django_db
@pytest.mark.parametrize("proxy_value, expected_secure", [(None, False), ("https", True), ("http", False)])
def test_editor_preview_preserves_proxy_tls_scheme(rf, post, mocker, settings, proxy_value, expected_secure):
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    headers = {} if proxy_value is None else {"HTTP_X_FORWARDED_PROTO": proxy_value}
    request = rf.get("/", **headers)
    spy = mocker.spy(Post, "get_preview_context")
    response = render_editor_preview(post, request)
    assert response.status_code == 200
    assert spy.call_args.args[1].is_secure() is expected_secure
    assert not spy.call_args.args[1].user.is_authenticated
