import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import override_settings
from django.template.loader import get_template
from django.template import Context, Template
from django.template.exceptions import TemplateSyntaxError
from django.urls import reverse
from django_comments import get_form_target
from django_comments import get_model as get_comments_model
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


def test_comment_form_helper_respects_runtime_comment_css_settings():
    from cast.comments.helper import CommentFormHelper

    with override_settings(
        CAST_COMMENTS_FORM_CSS_CLASS="comments-form compact",
        CAST_COMMENTS_LABEL_CSS_CLASS="col-sm-3",
        CAST_COMMENTS_FIELD_CSS_CLASS="col-sm-9",
    ):
        helper = CommentFormHelper()

    assert helper.form_class == "js-comments-form comments-form compact"
    assert helper.label_class == "col-sm-3"
    assert helper.field_class == "col-sm-9"


def test_comment_appsettings_unknown_attribute_raises():
    from cast.comments import appsettings

    with pytest.raises(AttributeError):
        getattr(appsettings, "NONEXISTENT_SETTING")


def test_comment_appsettings_falls_back_to_bootstrap4_crispy_templates(monkeypatch):
    from cast.comments import appsettings

    monkeypatch.delattr(settings, "CRISPY_TEMPLATE_PACK", raising=False)

    assert appsettings.CRISPY_TEMPLATE_PACK == "bootstrap4"
    get_template(f"{appsettings.CRISPY_TEMPLATE_PACK}/layout/field_errors.html")


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
def test_cast_comment_form_builds_helper_with_runtime_comment_css_settings(post):
    from django_comments import get_form

    with override_settings(CAST_COMMENTS_FORM_CSS_CLASS="comments-form compact"):
        form = get_form()(post)

    assert form.helper.form_class == "js-comments-form comments-form compact"


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

    # Import the forms module *before* patching: CastCommentForm's base class is
    # chosen once at first import (threaded vs. plain). Triggering that first
    # import via get_form() while USE_THREADEDCOMMENTS is patched to False would
    # bake a parent-less form class into sys.modules for the rest of the test
    # session, breaking later reply tests depending on test order.
    from cast.comments import forms  # noqa: F401

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
def test_comments_are_open_avoids_db_queries_with_repository(post, comments_enabled):
    from django.db import connection, reset_queries

    from cast.comments.utils import comments_are_open
    from cast.models import Post
    from cast.models.repository import PostDetailContext

    def blocker(*_args, **_kwargs):
        raise Exception("No database access allowed here.")

    post_for_repo = Post.objects.get(pk=post.pk)
    blog = post_for_repo.get_parent().specific
    repository = PostDetailContext(
        post_id=post.pk,
        template_base_dir="bootstrap4",
        blog=blog,
        root_nav_links=[],
        comments_are_enabled=True,
        has_audio=False,
        page_url="/some-post/",
        absolute_page_url="http://testserver/some-post/",
        owner_username="owner",
        blog_url="/some-blog/",
        cover_image_url="",
        cover_alt_text="",
        audio_by_id={},
        video_by_id={},
        image_by_id={},
        renditions_for_posts={},
    )
    post = Post.objects.get(pk=post.pk)
    post._repository = repository

    reset_queries()
    with connection.execute_wrapper(blocker):
        assert comments_are_open(post) is True


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
def test_templatetags_ajax_comment_tags_renders_for_syntax(post):
    html = Template("{% load fluent_comments_tags %}{% ajax_comment_tags for post %}").render(Context({"post": post}))
    assert "comment-added-message" in html


def test_templatetags_ajax_comment_tags_invalid_syntax_raises():
    with pytest.raises(TemplateSyntaxError):
        Template("{% load fluent_comments_tags %}{% ajax_comment_tags for a b %}")


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


def _valid_comment_payload(post):
    timestamp, security_hash = _security_data_from_form(post)
    return {
        "content_type": "cast.post",
        "object_pk": str(post.pk),
        "comment": "Hello",
        "name": "Name",
        "email": "a@example.com",
        "title": "Title",
        "timestamp": timestamp,
        "security_hash": security_hash,
    }


def _reply_payload(post, parent):
    data = _valid_comment_payload(post)
    data["parent"] = str(parent.pk)
    return data


@pytest.mark.django_db
@pytest.mark.parametrize("author_edits", [False, True])
def test_post_comment_ajax_rejects_parent_from_another_target(
    client, post, blog, settings, comments_enabled, author_edits
):
    from tests.factories import PostFactory

    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = author_edits
    from cast.comments import author_edits as author_edit_helpers

    assert author_edit_helpers.author_edits_enabled() is author_edits
    other_post = PostFactory(parent=blog, title="Other post", slug="other-comment-post", comments_enabled=True)
    parent = get_comments_model().objects.create(
        content_object=other_post, site_id=settings.SITE_ID, comment="private ancestor"
    )

    response = client.post(
        reverse("comments-post-comment-ajax"),
        _reply_payload(post, parent),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    assert get_comments_model().objects.filter(parent=parent).count() == 0


@pytest.mark.django_db
def test_post_comment_ajax_rejects_cross_site_parent(client, post, settings, comments_enabled):
    from django.contrib.sites.models import Site

    other_site = Site.objects.create(domain="ajax-comments.example", name="AJAX Comments")
    parent = get_comments_model().objects.create(content_object=post, site=other_site, comment="cross-site ancestor")

    response = client.post(
        reverse("comments-post-comment-ajax"),
        _reply_payload(post, parent),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    assert get_comments_model().objects.filter(parent=parent).count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(("is_public", "is_removed"), [(False, False), (True, True)])
def test_post_comment_ajax_rejects_hidden_parent(client, post, settings, comments_enabled, is_public, is_removed):
    parent = get_comments_model().objects.create(
        content_object=post,
        site_id=settings.SITE_ID,
        comment="hidden ancestor",
        is_public=is_public,
        is_removed=is_removed,
    )

    response = client.post(
        reverse("comments-post-comment-ajax"),
        _reply_payload(post, parent),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    assert get_comments_model().objects.filter(parent=parent).count() == 0


@pytest.mark.django_db
def test_post_comment_rejects_cross_site_parent(client, post, settings, comments_enabled):
    from django.contrib.sites.models import Site

    other_site = Site.objects.create(domain="comments.example", name="Comments")
    parent = get_comments_model().objects.create(content_object=post, site=other_site, comment="cross-site ancestor")

    response = client.post(reverse("comments-post-comment"), _reply_payload(post, parent))

    assert response.status_code == 400
    assert get_comments_model().objects.filter(parent=parent).count() == 0


@pytest.mark.django_db
def test_post_comment_rejects_parent_from_another_target(client, post, blog, settings, comments_enabled):
    from tests.factories import PostFactory

    other_post = PostFactory(parent=blog, title="Other stock post", slug="other-stock-comment-post")
    parent = get_comments_model().objects.create(
        content_object=other_post, site_id=settings.SITE_ID, comment="foreign ancestor"
    )

    response = client.post(reverse("comments-post-comment"), _reply_payload(post, parent))

    assert response.status_code == 400
    assert get_comments_model().objects.filter(parent=parent).count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(("is_public", "is_removed"), [(False, False), (True, True)])
def test_post_comment_rejects_hidden_parent(client, post, settings, comments_enabled, is_public, is_removed):
    parent = get_comments_model().objects.create(
        content_object=post,
        site_id=settings.SITE_ID,
        comment="hidden ancestor",
        is_public=is_public,
        is_removed=is_removed,
    )

    response = client.post(reverse("comments-post-comment"), _reply_payload(post, parent))

    assert response.status_code == 400
    assert get_comments_model().objects.filter(parent=parent).count() == 0


@pytest.mark.django_db
def test_post_comment_rejects_missing_parent(client, post, comments_enabled):
    data = _valid_comment_payload(post)
    data["parent"] = "99999999"

    response = client.post(reverse("comments-post-comment"), data)

    assert response.status_code == 400
    assert get_comments_model().objects.count() == 0


@pytest.mark.django_db
def test_post_comment_allows_valid_reply(client, post, settings, comments_enabled):
    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="visible ancestor"
    )

    response = client.post(reverse("comments-post-comment"), _reply_payload(post, parent))

    assert response.status_code == 302
    assert get_comments_model().objects.filter(parent=parent, comment="Hello").exists()


@pytest.mark.django_db
def test_post_comment_reply_requires_csrf(client, post, settings, comments_enabled):
    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="visible ancestor"
    )
    settings.MIDDLEWARE = [
        middleware for middleware in settings.MIDDLEWARE if middleware != "django.middleware.csrf.CsrfViewMiddleware"
    ]
    client.handler.enforce_csrf_checks = True

    response = client.post(reverse("comments-post-comment"), _reply_payload(post, parent))

    assert response.status_code == 403
    assert not get_comments_model().objects.filter(parent=parent).exists()


@pytest.mark.django_db
def test_post_comment_reply_delegates_invalid_form_to_stock_view(client, post, settings, comments_enabled):
    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="visible ancestor"
    )
    data = _reply_payload(post, parent)
    data["security_hash"] += "invalid"

    response = client.post(reverse("comments-post-comment"), data)

    assert response.status_code == 400
    assert not get_comments_model().objects.filter(parent=parent).exists()


@pytest.mark.django_db
def test_post_comment_reply_preview_delegates_to_stock_view(client, post, settings, comments_enabled):
    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="visible ancestor"
    )
    data = _reply_payload(post, parent)
    data["preview"] = "1"

    response = client.post(reverse("comments-post-comment"), data)

    assert response.status_code == 200
    assert b"Preview" in response.content
    assert not get_comments_model().objects.filter(parent=parent).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("name", "email", "expected_name", "expected_email"),
    [
        ("", "", None, None),
        ("Given Name", "", "Given Name", None),
        ("", "given@example.com", None, "given@example.com"),
    ],
)
def test_post_comment_authenticated_reply_fills_identity(
    client, post, user, settings, comments_enabled, name, email, expected_name, expected_email
):
    raw_password = user._password
    user.first_name = "Account"
    user.last_name = "Owner"
    user.email = "account-owner@example.com"
    user.save(update_fields=["first_name", "last_name", "email"])
    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="visible ancestor"
    )
    assert client.login(username=user.username, password=raw_password)
    data = _reply_payload(post, parent)
    data["name"] = name
    data["email"] = email

    response = client.post(reverse("comments-post-comment"), data)

    assert response.status_code == 302
    saved = get_comments_model().objects.get(parent=parent)
    expected_saved_name = expected_name if expected_name is not None else user.get_full_name()
    expected_saved_email = expected_email if expected_email is not None else user.email
    assert saved.user == user
    assert saved.user_name == expected_saved_name
    assert saved.user_email == expected_saved_email


@pytest.mark.django_db
def test_post_comment_reply_signal_can_reject(client, post, settings, comments_enabled):
    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="visible ancestor"
    )

    def reject_reply(sender, comment, request, **kwargs):
        return False

    signals.comment_will_be_posted.connect(reject_reply, dispatch_uid="reject_stock_reply_test")
    try:
        response = client.post(reverse("comments-post-comment"), _reply_payload(post, parent))
    finally:
        signals.comment_will_be_posted.disconnect(dispatch_uid="reject_stock_reply_test")

    assert response.status_code == 400
    assert not get_comments_model().objects.filter(parent=parent).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(("is_public", "is_removed"), [(False, False), (True, True)])
def test_safe_fill_tree_filters_hidden_ancestor_without_dropping_paginated_reply(
    post, settings, is_public, is_removed
):
    grandparent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="visible grandparent"
    )
    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, parent=grandparent, comment="hidden ancestor"
    )
    reply = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, parent=parent, comment="visible reply"
    )
    parent.is_public = is_public
    parent.is_removed = is_removed
    parent.save(update_fields=["is_public", "is_removed"])

    html = Template("{% load fluent_comments_tags %}{% fluent_comments_list %}").render(
        Context({"comment_list": [reply], "request": None})
    )

    assert "hidden ancestor" not in html
    assert "visible grandparent" not in html
    assert "visible reply" in html
    assert html.count('<ul class="comment-list-wrapper">') == html.count("</ul>")

    html_with_root = Template("{% load fluent_comments_tags %}{% fluent_comments_list %}").render(
        Context({"comment_list": [grandparent, reply], "request": None})
    )
    assert "visible grandparent" in html_with_root
    assert "hidden ancestor" not in html_with_root
    assert "visible reply" in html_with_root
    assert html_with_root.count('<ul class="comment-list-wrapper">') == html_with_root.count("</ul>")

    from cast.comments.templatetags.fluent_comments_tags import safe_fill_tree

    rendered = safe_fill_tree([grandparent, reply])
    assert rendered[-1].parent_id == grandparent.pk


@pytest.mark.django_db
def test_safe_fill_tree_clears_primed_excluded_parent_cache(post, settings):
    from cast.comments.templatetags.fluent_comments_tags import safe_fill_tree

    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="hidden ancestor", is_public=False
    )
    reply = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, parent=parent, comment="visible reply"
    )
    reply = get_comments_model().objects.select_related("parent").get(pk=reply.pk)
    original_tree_path = reply.tree_path
    assert reply.parent == parent
    assert "parent" in reply._state.fields_cache

    (rendered_reply,) = safe_fill_tree([reply])

    assert rendered_reply.parent_id is None
    assert rendered_reply.parent is None
    assert reply.parent_id == parent.pk
    assert reply.tree_path == original_tree_path
    assert reply.parent == parent


@pytest.mark.django_db
def test_safe_fill_tree_filters_malformed_cross_target_ancestor(post, blog, settings):
    from threadedcomments.models import PATH_SEPARATOR
    from tests.factories import PostFactory

    other_post = PostFactory(parent=blog, title="Other post", slug="other-render-post")
    foreign_parent = get_comments_model().objects.create(
        content_object=other_post, site_id=settings.SITE_ID, comment="foreign ancestor"
    )
    reply = get_comments_model().objects.create(content_object=post, site_id=settings.SITE_ID, comment="visible reply")
    get_comments_model().objects.filter(pk=reply.pk).update(
        tree_path=PATH_SEPARATOR.join((foreign_parent.tree_path, reply.tree_path))
    )
    reply.refresh_from_db()

    html = Template("{% load fluent_comments_tags %}{% fluent_comments_list %}").render(
        Context({"comment_list": [reply], "request": None})
    )

    assert "foreign ancestor" not in html
    assert "visible reply" in html
    assert html.count('<ul class="comment-list-wrapper">') == html.count("</ul>")


@pytest.mark.django_db
def test_threadedcomments_fill_tree_is_replaced_with_safe_filter(post, blog, settings):
    from threadedcomments.models import PATH_SEPARATOR
    from tests.factories import PostFactory

    other_post = PostFactory(parent=blog, title="Other override post", slug="other-override-post")
    foreign_parent = get_comments_model().objects.create(
        content_object=other_post, site_id=settings.SITE_ID, comment="foreign ancestor"
    )
    reply = get_comments_model().objects.create(content_object=post, site_id=settings.SITE_ID, comment="visible reply")
    get_comments_model().objects.filter(pk=reply.pk).update(
        tree_path=PATH_SEPARATOR.join((foreign_parent.tree_path, reply.tree_path))
    )
    reply.refresh_from_db()

    html = Template(
        "{% load threadedcomments_tags %}{% for item in comments|fill_tree %}{{ item.comment }}{% endfor %}"
    ).render(Context({"comments": [reply]}))

    assert "foreign ancestor" not in html
    assert "visible reply" in html


@pytest.mark.django_db
def test_safe_fill_tree_ignores_invalid_path_segment(post, settings):
    reply = get_comments_model().objects.create(content_object=post, site_id=settings.SITE_ID, comment="visible reply")
    get_comments_model().objects.filter(pk=reply.pk).update(tree_path=f"invalid/{reply.tree_path}")
    reply.refresh_from_db()

    html = Template("{% load fluent_comments_tags %}{% fluent_comments_list %}").render(
        Context({"comment_list": [reply], "request": None})
    )

    assert "visible reply" in html


@pytest.mark.django_db
def test_safe_fill_tree_keeps_visible_ancestor_for_paginated_reply(post, settings):
    parent = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, comment="visible ancestor"
    )
    reply = get_comments_model().objects.create(
        content_object=post, site_id=settings.SITE_ID, parent=parent, comment="visible reply"
    )

    html = Template("{% load fluent_comments_tags %}{% fluent_comments_list %}").render(
        Context({"comment_list": [reply], "request": None})
    )

    assert "visible ancestor" in html
    assert "visible reply" in html


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
def test_post_comment_ajax_invalid_content_type_without_model_returns_bad_request(client, post):
    ajax_url = reverse("comments-post-comment-ajax")
    r = client.post(
        ajax_url,
        {"content_type": "cast", "object_pk": str(post.pk)},
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
def test_post_comment_ajax_security_errors_return_bad_request(client, post, comments_enabled):
    ajax_url = reverse("comments-post-comment-ajax")
    data = _valid_comment_payload(post)
    data["security_hash"] += "broken"
    r = client.post(
        ajax_url,
        data,
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert r.status_code == 400


@pytest.mark.django_db
def test_post_comment_ajax_rejects_closed_comments(client, post, comments_enabled):
    ajax_url = reverse("comments-post-comment-ajax")
    post.comments_enabled = False
    post.save()

    response = client.post(
        ajax_url,
        _valid_comment_payload(post),
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )

    assert response.status_code == 400
    assert get_comments_model().objects.count() == 0


@pytest.mark.django_db
def test_post_comment_rejects_closed_comments(client, post, comments_enabled):
    post.comments_enabled = False
    post.save()

    response = client.post(reverse("comments-post-comment"), _valid_comment_payload(post))

    assert response.status_code == 400
    assert get_comments_model().objects.count() == 0


@pytest.mark.django_db
def test_post_comment_get_delegates_to_stock_view(client):
    response = client.get(reverse("comments-post-comment"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_post_comment_invalid_target_returns_bad_request(client):
    response = client.post(reverse("comments-post-comment"), {"content_type": "cast.post", "object_pk": "bad"})

    assert response.status_code == 400
    assert get_comments_model().objects.count() == 0


@pytest.mark.django_db
def test_post_comment_ajax_preview_success(client, post, comments_enabled):
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
def test_post_comment_ajax_returns_form_errors(client, post, comments_enabled):
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
def test_post_comment_ajax_comment_will_be_posted_can_kill_comment(client, post, comments_enabled):
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
def test_post_comment_ajax_authenticated_user_auto_fills_name_and_email(client, post, user, comments_enabled):
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
def test_post_comment_ajax_authenticated_user_keeps_given_name_and_email(client, post, user, comments_enabled):
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
