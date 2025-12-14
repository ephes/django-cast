import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.template import Context, Template
from django.urls import reverse
from django_comments import get_form_target
from django_comments import signals
from django_comments.forms import CommentForm


@pytest.mark.django_db
def test_post_get_absolute_url_returns_full_url(post):
    assert post.get_absolute_url() == post.full_url


@pytest.mark.django_db
def test_comment_form_helper_sets_action_and_attrs(post):
    from django_comments import get_form

    from cast.comments.helper import CommentFormHelper

    form = get_form()(post)
    helper = CommentFormHelper(form=form)
    assert helper.form_action == get_form_target()
    assert helper.form_id == f"comment-form-{post.pk}"
    assert helper.attrs == {"data-object-id": post.pk}


@pytest.mark.django_db
def test_get_base_form_supports_non_threaded(monkeypatch):
    from cast.comments import appsettings
    from cast.comments import forms as cast_comment_forms

    monkeypatch.setattr(appsettings, "USE_THREADEDCOMMENTS", False)
    assert cast_comment_forms._get_base_form() is CommentForm


@pytest.mark.django_db
def test_cast_comment_form_invalid_exclude_field_raises(monkeypatch, post):
    from cast.comments import appsettings
    from cast.comments.forms import CastCommentForm

    monkeypatch.setattr(appsettings, "EXCLUDE_FIELDS", ("does_not_exist",))
    with pytest.raises(ImproperlyConfigured):
        CastCommentForm(post)


@pytest.mark.django_db
def test_cast_comment_form_fills_excluded_fields(monkeypatch, post):
    from django_comments import get_form

    from cast.comments import appsettings

    monkeypatch.setattr(appsettings, "EXCLUDE_FIELDS", ("url",))
    form = get_form()(post)
    data = {
        "content_type": "cast.post",
        "object_pk": str(post.pk),
        "timestamp": str(form["timestamp"].value()),
        "security_hash": str(form["security_hash"].value()),
        "honeypot": "",
        "parent": "",
        "name": "Name",
        "email": "test@example.com",
        "title": "Title",
        "comment": "Hello",
    }

    bound = get_form()(post, data=data, is_preview=False)
    assert bound.is_valid()
    assert "url" not in bound.cleaned_data

    bound.get_comment_create_data()
    assert bound.cleaned_data["url"] == ""


@pytest.mark.django_db
def test_cast_comment_form_keeps_existing_excluded_cleaned_data(monkeypatch, post):
    from django_comments import get_form

    from cast.comments import appsettings

    monkeypatch.setattr(appsettings, "EXCLUDE_FIELDS", ("url",))
    form = get_form()(post)
    data = {
        "content_type": "cast.post",
        "object_pk": str(post.pk),
        "timestamp": str(form["timestamp"].value()),
        "security_hash": str(form["security_hash"].value()),
        "honeypot": "",
        "parent": "",
        "name": "Name",
        "email": "test@example.com",
        "title": "Title",
        "comment": "Hello",
    }

    bound = get_form()(post, data=data, is_preview=False)
    assert bound.is_valid()
    bound.cleaned_data["url"] = "https://example.com/"
    bound.get_comment_create_data()
    assert bound.cleaned_data["url"] == "https://example.com/"


@pytest.mark.django_db
def test_cast_comment_form_field_order_without_threadedcomments(monkeypatch, post):
    from django_comments import get_form

    from cast.comments import appsettings

    monkeypatch.setattr(appsettings, "USE_THREADEDCOMMENTS", False)
    form = get_form()(post)
    fields = list(form.fields.keys())
    assert fields[:4] == ["content_type", "object_pk", "timestamp", "security_hash"]


@pytest.mark.django_db
def test_models_get_base_comment_model_supports_threaded_and_non_threaded(monkeypatch):
    from cast.comments import appsettings
    from cast.comments.models import get_base_comment_model
    from django_comments.models import Comment as DjangoComment
    from threadedcomments.models import ThreadedComment as ThreadedCommentModel

    monkeypatch.setattr(appsettings, "USE_THREADEDCOMMENTS", True)
    assert get_base_comment_model() is ThreadedCommentModel

    monkeypatch.setattr(appsettings, "USE_THREADEDCOMMENTS", False)
    assert get_base_comment_model() is DjangoComment


def test_receivers_load_default_moderator_branches(monkeypatch):
    from cast.comments import appsettings
    from cast.comments.receivers import NullModerator, load_default_moderator

    monkeypatch.setattr(appsettings, "DEFAULT_MODERATOR", "none")
    moderator = load_default_moderator()
    assert isinstance(moderator, NullModerator)
    assert moderator.allow(None, None, None) is True
    assert moderator.moderate(None, None, None) is False

    monkeypatch.setattr(appsettings, "DEFAULT_MODERATOR", "default")
    assert isinstance(load_default_moderator(), NullModerator)

    monkeypatch.setattr(appsettings, "DEFAULT_MODERATOR", "cast.comments.receivers.NullModerator")
    assert isinstance(load_default_moderator(), NullModerator)

    monkeypatch.setattr(appsettings, "DEFAULT_MODERATOR", "bad-value")
    with pytest.raises(ImproperlyConfigured):
        load_default_moderator()


def test_receivers_allow_false_short_circuits(monkeypatch):
    from cast.comments import receivers

    class DenyAll:
        def allow(self, comment, content_object, request):
            return False

        def moderate(self, comment, content_object, request):
            raise AssertionError("moderate() must not run when allow() is False")

    monkeypatch.setattr(receivers, "default_moderator", DenyAll())
    comment = type("C", (), {"content_object": object()})()
    assert receivers.on_comment_will_be_posted(sender=object, comment=comment, request=object()) is False


@pytest.mark.django_db
def test_utils_helpers(post, comment):
    from cast.comments.utils import (
        comments_are_moderated,
        comments_are_open,
        get_comment_context_data,
        get_comment_template_name,
    )

    class EnabledCallable:
        def comments_are_enabled(self):
            return False

    class EnabledAttr:
        comments_are_enabled = False

    class EnabledMissing:
        pass

    assert comments_are_open(EnabledCallable()) is False
    assert comments_are_open(EnabledAttr()) is False
    assert comments_are_open(EnabledMissing()) is True
    assert comments_are_moderated(post) is False

    template_names = get_comment_template_name(comment)
    assert template_names[0].startswith("comments/")
    ctx = get_comment_context_data(comment, action="preview")
    assert ctx["preview"] is True


@pytest.mark.django_db
def test_templatetags_render_comment_and_count(post, comment):
    html = Template(
        "{% load fluent_comments_tags %}"
        "{% with cnt=post|comments_count %}{{ cnt }}{% endwith %}"
        "{% render_comment comment %}"
    ).render(Context({"post": post, "comment": comment}))
    assert "1" in html
    assert 'class="comment-item"' in html


@pytest.mark.django_db
def test_templatetags_ajax_comment_tags_renders(post):
    html = Template("{% load fluent_comments_tags %}{% ajax_comment_tags post %}").render(Context({"post": post}))
    assert "comment-added-message" in html


@pytest.mark.django_db
def test_templatetags_fluent_comments_list_auto_target_object_id(post, comment):
    html = Template("{% load fluent_comments_tags %}{% fluent_comments_list %}").render(
        Context({"comment_list": [comment], "request": None})
    )
    assert f'data-object-id="{comment.object_pk}"' in html


@pytest.mark.django_db
def test_templatetags_filters_are_renderable(post):
    obj = type("Obj", (), {})()
    html = Template(
        "{% load fluent_comments_tags %}{{ obj|comments_are_open }} {{ obj|comments_are_moderated }}"
    ).render(Context({"obj": obj}))
    assert html.strip() == "True False"


@pytest.mark.django_db
def test_templatetags_fluent_comments_list_uses_explicit_target_object_id(monkeypatch):
    from cast.comments import appsettings

    monkeypatch.setattr(appsettings, "USE_THREADEDCOMMENTS", False)
    html = Template("{% load fluent_comments_tags %}{% fluent_comments_list %}").render(
        Context({"comment_list": [], "target_object_id": "123", "request": None})
    )
    assert 'data-object-id="123"' in html


@pytest.mark.django_db
def test_templatetags_fluent_comments_list_handles_broken_index(monkeypatch, post):
    from cast.comments import appsettings

    class WeirdList:
        def __bool__(self):
            return True

        def __iter__(self):
            return iter(())

        def __getitem__(self, idx):
            raise RuntimeError("boom")

    monkeypatch.setattr(appsettings, "USE_THREADEDCOMMENTS", False)
    html = Template("{% load fluent_comments_tags %}{% fluent_comments_list %}").render(
        Context({"comment_list": WeirdList(), "request": None})
    )
    assert 'class="comments' in html


def _security_data_from_form(post):
    from django_comments import get_form

    form = get_form()(post)
    return str(form["timestamp"].value()), str(form["security_hash"].value())


@pytest.mark.django_db
def test_post_comment_ajax_requires_ajax_header(client):
    ajax_url = reverse("comments-post-comment-ajax")
    r = client.post(ajax_url, {})
    assert r.status_code == 400
    assert "Expecting Ajax call" in r.content.decode("utf-8")


@pytest.mark.django_db
def test_post_comment_ajax_missing_required_fields(client):
    ajax_url = reverse("comments-post-comment-ajax")
    r = client.post(ajax_url, {}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_invalid_object_pk_returns_bad_request(client, post):
    ajax_url = reverse("comments-post-comment-ajax")
    r = client.post(
        ajax_url,
        {"content_type": "cast.post", "object_pk": "not-a-number"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_invalid_content_type_returns_bad_request(client, post):
    ajax_url = reverse("comments-post-comment-ajax")
    r = client.post(
        ajax_url,
        {"content_type": "noapp.nomodel", "object_pk": str(post.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_attribute_error_branch(client, mocker, post):
    ajax_url = reverse("comments-post-comment-ajax")

    class StubModel:
        pass

    from cast.comments import views as comment_views

    original_get_model = comment_views.apps.get_model

    def get_model_side_effect(*args, **kwargs):
        if args[:2] == ("cast", "post"):
            return StubModel()
        return original_get_model(*args, **kwargs)

    mocker.patch.object(comment_views.apps, "get_model", side_effect=get_model_side_effect)
    r = client.post(
        ajax_url,
        {"content_type": "cast.post", "object_pk": str(post.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_object_does_not_exist_branch(client):
    ajax_url = reverse("comments-post-comment-ajax")
    r = client.post(
        ajax_url,
        {"content_type": "cast.post", "object_pk": "99999999"},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_validation_error_branch(client, mocker, post):
    ajax_url = reverse("comments-post-comment-ajax")

    class StubManager:
        def using(self, using=None):
            return self

        def get(self, pk=None):
            raise ValidationError("bad")

    class StubModel:
        _default_manager = StubManager()

    from cast.comments import views as comment_views

    original_get_model = comment_views.apps.get_model

    def get_model_side_effect(*args, **kwargs):
        if args[:2] == ("cast", "post"):
            return StubModel()
        return original_get_model(*args, **kwargs)

    mocker.patch.object(comment_views.apps, "get_model", side_effect=get_model_side_effect)
    r = client.post(
        ajax_url,
        {"content_type": "cast.post", "object_pk": str(post.pk)},
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_security_errors_return_bad_request(client, post):
    ajax_url = reverse("comments-post-comment-ajax")
    timestamp, security_hash = _security_data_from_form(post)
    r = client.post(
        ajax_url,
        {
            "content_type": "cast.post",
            "object_pk": str(post.pk),
            "comment": "Hello",
            "name": "Name",
            "email": "a@example.com",
            "title": "Title",
            "timestamp": timestamp,
            "security_hash": security_hash + "broken",
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_preview_success(client, post):
    ajax_url = reverse("comments-post-comment-ajax")
    timestamp, security_hash = _security_data_from_form(post)
    r = client.post(
        ajax_url,
        {
            "content_type": "cast.post",
            "object_pk": str(post.pk),
            "comment": "Hello",
            "name": "Name",
            "email": "a@example.com",
            "title": "Title",
            "timestamp": timestamp,
            "security_hash": security_hash,
            "preview": "1",
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["action"] == "preview"
    assert 'id="comment-preview"' in data["html"]


@pytest.mark.django_db
def test_post_comment_ajax_returns_form_errors(client, post):
    ajax_url = reverse("comments-post-comment-ajax")
    timestamp, security_hash = _security_data_from_form(post)
    r = client.post(
        ajax_url,
        {
            "content_type": "cast.post",
            "object_pk": str(post.pk),
            "name": "Name",
            "email": "a@example.com",
            "title": "Title",
            "timestamp": timestamp,
            "security_hash": security_hash,
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is False
    assert "comment" in data["errors"]
    assert "<" in data["errors"]["comment"]


@pytest.mark.django_db
def test_post_comment_ajax_comment_will_be_posted_can_kill_comment(client, post):
    ajax_url = reverse("comments-post-comment-ajax")
    timestamp, security_hash = _security_data_from_form(post)

    def kill_comment(sender, comment, request, **kwargs):
        return False

    signals.comment_will_be_posted.connect(kill_comment, dispatch_uid="kill_comment_test")
    try:
        r = client.post(
            ajax_url,
            {
                "content_type": "cast.post",
                "object_pk": str(post.pk),
                "comment": "Hello",
                "name": "Name",
                "email": "a@example.com",
                "title": "Title",
                "timestamp": timestamp,
                "security_hash": security_hash,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
    finally:
        signals.comment_will_be_posted.disconnect(dispatch_uid="kill_comment_test")

    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_authenticated_user_auto_fills_name_and_email(client, post, user):
    from django_comments import get_model as get_comments_model

    ajax_url = reverse("comments-post-comment-ajax")
    timestamp, security_hash = _security_data_from_form(post)
    raw_password = user._password
    user.first_name = ""
    user.last_name = ""
    user.email = "alice@example.com"
    user.save()
    assert client.login(username=user.username, password=raw_password)

    r = client.post(
        ajax_url,
        {
            "content_type": "cast.post",
            "object_pk": str(post.pk),
            "comment": "Hello",
            "title": "Title",
            "timestamp": timestamp,
            "security_hash": security_hash,
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True

    saved = get_comments_model().objects.get(pk=data["comment_id"])
    assert saved.user_id == user.id
    assert saved.user_name == (user.get_full_name() or user.username)
    assert saved.user_email == user.email


@pytest.mark.django_db
def test_post_comment_ajax_authenticated_user_keeps_given_name_and_email(client, post, user):
    from django_comments import get_model as get_comments_model

    ajax_url = reverse("comments-post-comment-ajax")
    timestamp, security_hash = _security_data_from_form(post)
    raw_password = user._password
    assert client.login(username=user.username, password=raw_password)

    r = client.post(
        ajax_url,
        {
            "content_type": "cast.post",
            "object_pk": str(post.pk),
            "comment": "Hello",
            "title": "Title",
            "name": "Given Name",
            "email": "given@example.com",
            "timestamp": timestamp,
            "security_hash": security_hash,
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True

    saved = get_comments_model().objects.get(pk=data["comment_id"])
    assert saved.user_id == user.id
    assert saved.user_name == "Given Name"
    assert saved.user_email == "given@example.com"
