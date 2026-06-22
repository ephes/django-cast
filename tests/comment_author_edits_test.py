"""Tests for anonymous comment self-editing and deletion (author edits feature)."""

from importlib import import_module

import pytest
from django.conf import settings as dj_settings

from cast.comments import author_edits


def make_session():
    engine = import_module(dj_settings.SESSION_ENGINE)
    return engine.SessionStore()


class TestFeatureGuard:
    def test_disabled_by_default(self, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        assert author_edits.author_edits_enabled() is False

    def test_enabled_with_server_side_session_backend(self, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
        assert author_edits.author_edits_enabled() is True

    def test_disabled_with_signed_cookies_backend(self, settings):
        # Even with the flag on, the insecure client-side session backend must
        # disable the feature at runtime (no opt-out).
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
        assert author_edits.author_edits_enabled() is False

    def test_string_value_does_not_enable(self, settings):
        # bool("False") is True, so only the literal True may enable the feature;
        # a stray string must not silently turn on this opt-in feature.
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = "False"
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
        assert author_edits.author_edits_enabled() is False

    def test_truthy_string_true_does_not_enable(self, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = "True"
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
        assert author_edits.author_edits_enabled() is False

    def test_non_bool_setting_is_flagged_by_type_check(self, settings):
        from cast.checks import check_cast_setting_types

        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = "True"
        errors = check_cast_setting_types()
        assert any(e.id == "cast.E001" and "CAST_COMMENTS_ALLOW_AUTHOR_EDITS" in e.msg for e in errors)


class TestOwnership:
    def test_record_and_owns_normalizes_to_string(self):
        session = make_session()
        author_edits.record_owned_id(session, 42)
        assert author_edits.owns_id(session, 42) is True
        # A posted id arrives as a string and must still match.
        assert author_edits.owns_id(session, "42") is True
        assert author_edits.owns_id(session, 99) is False

    def test_owns_id_false_for_empty_session(self):
        session = make_session()
        assert author_edits.owns_id(session, 1) is False

    def test_owned_ids_are_capped_keeping_most_recent(self, settings):
        settings.CAST_COMMENTS_OWNED_IDS_CAP = 3
        session = make_session()
        for pk in range(1, 6):
            author_edits.record_owned_id(session, pk)
        # Oldest ids beyond the cap lose their affordance.
        assert author_edits.owns_id(session, 1) is False
        assert author_edits.owns_id(session, 2) is False
        # The three most recent are retained.
        assert author_edits.owns_id(session, 3) is True
        assert author_edits.owns_id(session, 5) is True

    def test_recording_marks_session_modified(self):
        session = make_session()
        author_edits.record_owned_id(session, 1)
        assert session.modified is True

    def test_record_owned_id_is_idempotent(self):
        session = make_session()
        author_edits.record_owned_id(session, 5)
        author_edits.record_owned_id(session, 5)  # duplicate signal delivery
        assert session[author_edits.SESSION_KEY] == ["5"]

    def test_rate_limited_is_false_when_limit_zero(self, settings, rf):
        settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 0
        assert author_edits.rate_limited(rf.post("/"), "edit") is False


class TestEligibility:
    pytestmark = pytest.mark.django_db

    def test_public_unanswered_comment_is_actionable(self, comment):
        assert author_edits.comment_is_actionable(comment) is True

    def test_removed_comment_is_not_actionable(self, comment):
        comment.is_removed = True
        comment.save()
        assert author_edits.comment_is_actionable(comment) is False

    def test_non_public_comment_is_not_actionable(self, comment):
        comment.is_public = False
        comment.save()
        assert author_edits.comment_is_actionable(comment) is False

    def test_answered_comment_is_not_actionable(self, comment, post, settings):
        # Any reply, even a hidden/pending one, freezes the parent.
        from django_comments import get_model as get_comments_model

        model = get_comments_model()
        reply = model(
            content_object=post,
            site_id=settings.SITE_ID,
            comment="a reply",
            parent=comment,
            is_public=False,
            is_removed=True,
        )
        reply.save()
        assert author_edits.comment_is_actionable(comment) is False

    def test_comment_has_reply_false_without_threadedcomments(self, comment, mocker):
        mocker.patch.object(author_edits.appsettings, "USE_THREADEDCOMMENTS", False)
        assert author_edits.comment_has_reply(comment) is False


class TestCommentAuthorMeta:
    pytestmark = pytest.mark.django_db

    def test_str_includes_comment_pk(self):
        from cast.comments.models import CommentAuthorMeta

        assert "42" in str(CommentAuthorMeta(comment_pk="42"))

    def test_mark_edited_sets_flag(self, comment):
        author_edits.mark_edited(comment)
        assert author_edits.edited_pks_for([comment.pk]) == {str(comment.pk)}

    def test_mark_deleted_records_timestamp_and_lists_pk(self, comment):
        author_edits.mark_deleted(comment)
        assert str(comment.pk) in author_edits.deleted_comment_pks()

    def test_clear_deleted_removes_pk_from_deleted_set(self, comment):
        author_edits.mark_deleted(comment)
        author_edits.clear_deleted(comment.pk)
        assert str(comment.pk) not in author_edits.deleted_comment_pks()


class TestAdminRegistration:
    def test_comment_author_meta_is_registered(self):
        from django.contrib import admin

        from cast.comments.models import CommentAuthorMeta

        assert CommentAuthorMeta in admin.site._registry


@pytest.fixture
def feature_on(settings):
    settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    return settings


def post_a_comment(client, post, text="hello world", parent=None):
    """Post a comment through the AJAX endpoint, scraping CSRF/security fields."""
    import re

    from django.urls import reverse

    content = client.get(post.get_url()).content.decode("utf-8")
    security_hash = re.search(r'name="security_hash"[^>]*value="([^"]+)"', content).group(1)
    timestamp = re.search(r'name="timestamp"[^>]*value="([^"]+)"', content).group(1)
    data = {
        "content_type": "cast.post",
        "object_pk": str(post.pk),
        "comment": text,
        "name": "Commenter",
        "email": "c@example.com",
        "title": "t",
        "security_hash": security_hash,
        "timestamp": timestamp,
    }
    if parent is not None:
        data["parent"] = str(parent.pk)
    return client.post(
        reverse("comments-post-comment-ajax"),
        data,
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )


def seed_ownership(client, comment):
    session = client.session
    session[author_edits.SESSION_KEY] = [str(comment.pk)]
    session.save()


AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class TestEditEndpoint:
    pytestmark = pytest.mark.django_db

    def test_owner_can_edit_text(self, client, comment, feature_on):
        from django.urls import reverse

        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "edited text"},
            **AJAX,
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        # comment_id is serialized as a string so UUID PKs do not break json.dumps.
        assert isinstance(r.json()["comment_id"], str)
        comment.refresh_from_db()
        assert comment.comment == "edited text"

    def test_non_owner_cannot_edit(self, client, comment, feature_on):
        from django.urls import reverse

        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "hacked"},
            **AJAX,
        )
        assert r.status_code in (403, 404)
        comment.refresh_from_db()
        assert comment.comment != "hacked"

    def test_feature_disabled_returns_404(self, client, comment, settings):
        from django.urls import reverse

        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "edited text"},
            **AJAX,
        )
        assert r.status_code == 404

    def test_identity_fields_are_immutable(self, client, comment, feature_on):
        from django.urls import reverse

        comment.user_name = "Original Author"
        comment.user_email = "orig@example.com"
        comment.save()
        seed_ownership(client, comment)
        client.post(
            reverse("comments-edit-comment-ajax"),
            {
                "comment_id": str(comment.pk),
                "comment": "new text",
                "name": "Impersonator",
                "email": "evil@example.com",
            },
            **AJAX,
        )
        comment.refresh_from_db()
        assert comment.user_name == "Original Author"
        assert comment.user_email == "orig@example.com"

    def test_answered_comment_cannot_be_edited(self, client, comment, post, settings, feature_on):
        from django.urls import reverse
        from django_comments import get_model as get_comments_model

        reply = get_comments_model()(content_object=post, site_id=settings.SITE_ID, comment="reply", parent=comment)
        reply.save()
        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "sneaky edit"},
            **AJAX,
        )
        assert r.status_code == 403
        comment.refresh_from_db()
        assert comment.comment != "sneaky edit"

    def test_empty_text_is_rejected(self, client, comment, feature_on):
        from django.urls import reverse

        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "   "},
            **AJAX,
        )
        assert r.status_code == 400
        comment.refresh_from_db()
        assert comment.comment == "bar baz"

    def test_edit_into_spam_re_moderates_to_hidden(self, client, comment, feature_on):
        from unittest.mock import patch
        from django.urls import reverse

        from cast.moderation import Moderator

        class PredictSpam:
            @staticmethod
            def predict_label(_):
                return "spam"

        class SpamFilter:
            def __init__(self, model):
                self.model = model

        seed_ownership(client, comment)
        with patch(
            "cast.comments.receivers.default_moderator",
            new=Moderator(type(comment), spamfilter=SpamFilter(PredictSpam())),
        ):
            r = client.post(
                reverse("comments-edit-comment-ajax"),
                {"comment_id": str(comment.pk), "comment": "buy cheap pills now"},
                **AJAX,
            )
        assert r.status_code == 200
        assert r.json()["is_public"] is False
        comment.refresh_from_db()
        assert comment.is_removed is True
        assert comment.is_public is False

    def test_edit_does_not_fire_comment_was_posted(self, client, comment, feature_on):
        from django.urls import reverse
        from django_comments import signals

        received = []

        def handler(sender, comment, request, **kwargs):
            received.append(comment)

        signals.comment_was_posted.connect(handler)
        try:
            seed_ownership(client, comment)
            client.post(
                reverse("comments-edit-comment-ajax"),
                {"comment_id": str(comment.pk), "comment": "edited"},
                **AJAX,
            )
        finally:
            signals.comment_was_posted.disconnect(handler)
        assert received == []

    def test_edit_sets_edited_marker(self, client, comment, feature_on):
        from django.urls import reverse

        seed_ownership(client, comment)
        client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "edited"},
            **AJAX,
        )
        assert author_edits.edited_pks_for([comment.pk]) == {str(comment.pk)}

    def test_non_ajax_request_rejected(self, client, comment, feature_on):
        from django.urls import reverse

        seed_ownership(client, comment)
        # No X-Requested-With header -> rejected by the shared guard.
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "x"},
        )
        assert r.status_code == 400

    def test_owned_but_missing_comment_is_denied(self, client, feature_on):
        from django.urls import reverse

        # Session "owns" an id that does not resolve to a comment -> locked load
        # raises and returns the generic denial.
        session = client.session
        session[author_edits.SESSION_KEY] = ["999999"]
        session.save()
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": "999999", "comment": "x"},
            **AJAX,
        )
        assert r.status_code == 403

    def test_honeypot_rejected(self, client, comment, feature_on):
        from django.urls import reverse

        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "x", "honeypot": "i am a bot"},
            **AJAX,
        )
        assert r.status_code == 400

    def test_too_long_text_rejected(self, client, comment, feature_on):
        from django.urls import reverse
        from django_comments.forms import COMMENT_MAX_LENGTH

        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "x" * (COMMENT_MAX_LENGTH + 1)},
            **AJAX,
        )
        assert r.status_code == 400

    def test_edit_rejected_when_a_receiver_kills_it(self, client, comment, feature_on):
        from unittest.mock import patch

        from django.urls import reverse

        class DenyModerator:
            def allow(self, comment, content_object, request):
                return False

            def moderate(self, comment, content_object, request):
                return False

        seed_ownership(client, comment)
        with patch("cast.comments.receivers.default_moderator", new=DenyModerator()):
            r = client.post(
                reverse("comments-edit-comment-ajax"),
                {"comment_id": str(comment.pk), "comment": "rejected text"},
                **AJAX,
            )
        assert r.status_code == 400
        comment.refresh_from_db()
        assert comment.comment != "rejected text"

    def test_edited_comment_html_keeps_controls_and_marker(self, client, comment, feature_on):
        from django.urls import reverse

        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": str(comment.pk), "comment": "edited body"},
            **AJAX,
        )
        html = r.json()["html"]
        assert "comment-edited-flag" in html
        assert "comment-edit-link" in html


class TestRenderCommentContext:
    pytestmark = pytest.mark.django_db

    def test_render_comment_list_marks_owned_comment_editable(
        self, client, post, comment, comments_enabled, feature_on
    ):
        # Own the comment in the client session, then render the post detail page.
        seed_ownership(client, comment)
        html = client.get(post.get_url()).content.decode("utf-8")
        # The edit control is rendered for the owned, actionable comment.
        assert "comment-edit-link" in html
        assert "comment-delete-link" in html

    def test_render_comment_list_no_controls_for_unowned(self, client, post, comment, comments_enabled, feature_on):
        html = client.get(post.get_url()).content.decode("utf-8")
        assert "comment-edit-link" not in html


class TestActionContext:
    pytestmark = pytest.mark.django_db

    def _request(self, client, comment, owned=True):
        from django.test import RequestFactory

        rf = RequestFactory()
        request = rf.get("/")
        request.session = client.session
        if owned:
            request.session[author_edits.SESSION_KEY] = [str(comment.pk)]
        return request

    def test_owned_actionable_comment_is_editable(self, client, comment, feature_on):
        ctx = author_edits.comment_action_context(self._request(client, comment), comment)
        assert ctx["can_edit"] is True
        assert ctx["can_delete"] is True

    def test_unowned_comment_is_not_editable(self, client, comment, feature_on):
        ctx = author_edits.comment_action_context(self._request(client, comment, owned=False), comment)
        assert ctx["can_edit"] is False
        assert ctx["can_delete"] is False

    def test_disabled_feature_yields_no_controls(self, client, comment, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        ctx = author_edits.comment_action_context(self._request(client, comment), comment)
        assert ctx["can_edit"] is False

    def test_edited_flag_from_precomputed_set(self, client, comment, feature_on):
        ctx = author_edits.comment_action_context(
            self._request(client, comment), comment, edited_pks={str(comment.pk)}
        )
        assert ctx["edited"] is True

    def test_disabled_feature_does_no_metadata_query(self, client, comment, settings, django_assert_num_queries):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        request = self._request(client, comment)
        with django_assert_num_queries(0):
            ctx = author_edits.comment_action_context(request, comment)
        assert ctx == {"can_edit": False, "can_delete": False, "edited": False}


class TestRateLimiting:
    pytestmark = pytest.mark.django_db

    def test_edit_endpoint_is_rate_limited(self, client, comment, feature_on, settings):
        from django.core.cache import cache
        from django.urls import reverse

        cache.clear()
        settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 2
        seed_ownership(client, comment)
        url = reverse("comments-edit-comment-ajax")
        data = {"comment_id": str(comment.pk), "comment": "edited"}
        statuses = [client.post(url, data, **AJAX).status_code for _ in range(5)]
        assert 429 in statuses


class TestReplyCoordination:
    pytestmark = pytest.mark.django_db

    def test_reply_to_healthy_parent_succeeds(self, client, post, comment, comments_enabled, feature_on):
        r = post_a_comment(client, post, text="a reply", parent=comment)
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_reply_to_author_deleted_parent_is_rejected(self, client, post, comment, comments_enabled, feature_on):
        from django_comments import get_model as get_comments_model

        # The parent is author-deleted (hidden) before the racing reply lands.
        comment.is_removed = True
        comment.is_public = False
        comment.save()
        before = get_comments_model().objects.count()
        r = post_a_comment(client, post, text="late reply", parent=comment)
        assert r.status_code == 400
        # No child comment was created under the removed parent.
        assert get_comments_model().objects.count() == before

    def test_reply_to_nonexistent_parent_is_rejected(self, client, post, comments_enabled, feature_on):
        import re

        from django.urls import reverse
        from django_comments import get_model as get_comments_model

        content = client.get(post.get_url()).content.decode("utf-8")
        security_hash = re.search(r'name="security_hash"[^>]*value="([^"]+)"', content).group(1)
        timestamp = re.search(r'name="timestamp"[^>]*value="([^"]+)"', content).group(1)
        data = {
            "content_type": "cast.post",
            "object_pk": str(post.pk),
            "comment": "orphan reply",
            "name": "Commenter",
            "email": "c@example.com",
            "title": "t",
            "security_hash": security_hash,
            "timestamp": timestamp,
            "parent": "999999",  # no such parent
        }
        before = get_comments_model().objects.count()
        r = client.post(reverse("comments-post-comment-ajax"), data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        assert r.status_code == 400
        assert get_comments_model().objects.count() == before

    def test_stock_non_ajax_reply_is_blocked_when_feature_enabled(
        self, client, post, comment, comments_enabled, feature_on
    ):
        # The unlocked stock reply path is closed entirely while the feature is on:
        # replies (parent set) must go through the AJAX endpoint. The parent here is
        # perfectly healthy, yet the stock reply is still rejected.
        import re

        from django.urls import reverse
        from django_comments import get_model as get_comments_model

        content = client.get(post.get_url()).content.decode("utf-8")
        security_hash = re.search(r'name="security_hash"[^>]*value="([^"]+)"', content).group(1)
        timestamp = re.search(r'name="timestamp"[^>]*value="([^"]+)"', content).group(1)
        data = {
            "content_type": "cast.post",
            "object_pk": str(post.pk),
            "comment": "stock reply",
            "name": "Commenter",
            "email": "c@example.com",
            "title": "t",
            "security_hash": security_hash,
            "timestamp": timestamp,
            "parent": str(comment.pk),
        }
        before = get_comments_model().objects.count()
        r = client.post(reverse("comments-post-comment"), data)  # no AJAX header → stock view
        assert r.status_code == 400
        assert get_comments_model().objects.count() == before


class TestTunablesCheck:
    def _check(self):
        from cast.checks import check_cast_comments_author_edits_tunables

        return check_cast_comments_author_edits_tunables()

    def test_unset_tunables_pass(self, settings):
        assert self._check() == []

    def test_valid_tunables_pass(self, settings):
        settings.CAST_COMMENTS_OWNED_IDS_CAP = 100
        settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 10
        settings.CAST_COMMENTS_EDIT_RATE_WINDOW = 30
        assert self._check() == []

    def test_negative_value_flagged(self, settings):
        settings.CAST_COMMENTS_OWNED_IDS_CAP = -5
        assert [e.id for e in self._check()] == ["cast.E007"]

    def test_non_integer_value_flagged(self, settings):
        settings.CAST_COMMENTS_EDIT_RATE_LIMIT = "lots"
        assert [e.id for e in self._check()] == ["cast.E007"]

    def test_bool_value_flagged(self, settings):
        settings.CAST_COMMENTS_EDIT_RATE_WINDOW = True
        assert [e.id for e in self._check()] == ["cast.E007"]

    def test_zero_window_flagged(self, settings):
        # cap/limit may be 0 (no cap / disabled), but the window must be positive.
        settings.CAST_COMMENTS_EDIT_RATE_WINDOW = 0
        assert [e.id for e in self._check()] == ["cast.E007"]

    def test_zero_cap_and_limit_pass(self, settings):
        settings.CAST_COMMENTS_OWNED_IDS_CAP = 0
        settings.CAST_COMMENTS_EDIT_RATE_LIMIT = 0
        assert self._check() == []


class TestSessionlessRequests:
    pytestmark = pytest.mark.django_db

    def test_guard_denies_request_without_session(self, rf, settings):
        # Defensive: if the feature is enabled but the request has no session
        # (no SessionMiddleware), the guard denies instead of raising. This also
        # exercises rate_limited's no-session (IP-based) path.
        from django.core.cache import cache

        from cast.comments import views

        cache.clear()
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
        request = rf.post("/", {"comment_id": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        result = views._author_action_guard(request, "editing")
        assert result is not None and result.status_code == 403

    def test_record_owned_comment_without_session_is_noop(self, comment, rf, settings):
        from cast.comments import receivers

        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
        # No session on the request -> the receiver returns without raising.
        receivers.record_owned_comment(sender=type(comment), comment=comment, request=rf.post("/"))


class TestSessionRequirementCheck:
    def _check(self):
        from cast.checks import check_cast_comments_author_edits_requires_sessions

        return check_cast_comments_author_edits_requires_sessions()

    def test_feature_off_passes(self, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        assert self._check() == []

    def test_feature_on_with_sessions_configured_passes(self, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        assert self._check() == []

    def test_missing_sessions_app_flagged(self, settings, mocker):
        # The check resolves the app via the registry (apps.is_installed), which
        # accepts both the plain string and the SessionsConfig path; mock it to
        # simulate the app being absent.
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        mocker.patch("cast.checks.apps.is_installed", return_value=False)
        assert [e.id for e in self._check()] == ["cast.E008"]

    def test_missing_session_middleware_flagged(self, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "SessionMiddleware" not in m]
        assert [e.id for e in self._check()] == ["cast.E008"]


class TestSystemCheck:
    def test_error_when_enabled_with_signed_cookies(self, settings):
        from cast.checks import check_cast_comments_author_edits_session_backend

        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
        errors = check_cast_comments_author_edits_session_backend()
        assert [e.id for e in errors] == ["cast.E006"]

    def test_no_error_with_server_side_backend(self, settings):
        from cast.checks import check_cast_comments_author_edits_session_backend

        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = True
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
        assert check_cast_comments_author_edits_session_backend() == []

    def test_no_error_when_feature_disabled(self, settings):
        from cast.checks import check_cast_comments_author_edits_session_backend

        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
        assert check_cast_comments_author_edits_session_backend() == []


class TestTrainingExclusion:
    pytestmark = pytest.mark.django_db

    def test_author_deleted_excluded_but_moderator_removed_kept(self, comment, comment_spam):
        from cast.models.moderation import SpamFilter

        # Author-delete the legitimate comment ("bar baz").
        comment.is_removed = True
        comment.is_public = False
        comment.save()
        author_edits.mark_deleted(comment)

        train = SpamFilter.get_training_data_comments()
        messages = [message for _label, message in train]

        # The author-deleted comment is excluded from the corpus entirely.
        assert all("bar baz" not in message for message in messages)
        # The moderator-removed comment ("asdf bsdf") is still a spam example.
        spam_labels = [label for label, message in train if "asdf bsdf" in message]
        assert spam_labels == ["spam"]


class TestReceivers:
    pytestmark = pytest.mark.django_db

    def test_restoring_comment_clears_deleted_at(self, comment):
        comment.is_removed = True
        comment.is_public = False
        comment.save()
        author_edits.mark_deleted(comment)
        assert str(comment.pk) in author_edits.deleted_comment_pks()

        # Staff restore via the normal comment admin (un-remove): clears the marker.
        comment.is_removed = False
        comment.is_public = True
        comment.save()
        assert str(comment.pk) not in author_edits.deleted_comment_pks()

    def test_un_remove_only_clears_deleted_at_even_if_not_public(self, comment):
        comment.is_removed = True
        comment.is_public = False
        comment.save()
        author_edits.mark_deleted(comment)
        # Staff un-remove without restoring public visibility.
        comment.is_removed = False
        comment.save()
        assert str(comment.pk) not in author_edits.deleted_comment_pks()

    def test_hard_delete_removes_meta_row(self, comment):
        from cast.comments.models import CommentAuthorMeta

        author_edits.mark_edited(comment)
        pk = str(comment.pk)
        assert CommentAuthorMeta.objects.filter(comment_pk=pk).exists()
        comment.delete()
        assert not CommentAuthorMeta.objects.filter(comment_pk=pk).exists()


class TestPostRecordsOwnership:
    pytestmark = pytest.mark.django_db

    def test_posting_records_ownership_when_enabled(self, client, post, comments_enabled, feature_on):
        r = post_a_comment(client, post)
        assert r.status_code == 200
        new_id = str(r.json()["comment_id"])
        assert new_id in client.session.get(author_edits.SESSION_KEY, [])

    def test_posted_comment_html_includes_edit_delete_controls(self, client, post, comments_enabled, feature_on):
        # A freshly AJAX-posted comment is inserted by the JS using the response
        # html, so that html must already carry the owner's edit/delete controls
        # (and the raw-text source) — otherwise they only appear after a reload.
        r = post_a_comment(client, post)
        assert r.status_code == 200
        html = r.json()["html"]
        assert "comment-edit-link" in html
        assert "comment-delete-link" in html
        assert "comment-raw" in html

    def test_owner_can_then_edit_their_posted_comment(self, client, post, comments_enabled, feature_on):
        from django.urls import reverse

        new_id = str(post_a_comment(client, post).json()["comment_id"])
        r = client.post(
            reverse("comments-edit-comment-ajax"),
            {"comment_id": new_id, "comment": "edited after posting"},
            **AJAX,
        )
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_stock_post_view_also_records_ownership(self, client, post, comments_enabled, feature_on):
        import re

        from django.urls import reverse
        from django_comments import get_model as get_comments_model

        content = client.get(post.get_url()).content.decode("utf-8")
        security_hash = re.search(r'name="security_hash"[^>]*value="([^"]+)"', content).group(1)
        timestamp = re.search(r'name="timestamp"[^>]*value="([^"]+)"', content).group(1)
        client.post(
            reverse("comments-post-comment"),
            {
                "content_type": "cast.post",
                "object_pk": str(post.pk),
                "comment": "via stock view",
                "name": "Commenter",
                "email": "c@example.com",
                "title": "t",
                "security_hash": security_hash,
                "timestamp": timestamp,
            },
        )
        new = get_comments_model().objects.latest("id")
        assert str(new.pk) in client.session.get(author_edits.SESSION_KEY, [])

    def test_posting_does_not_write_session_when_disabled(self, client, post, comments_enabled, settings):
        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        r = post_a_comment(client, post)
        assert r.status_code == 200
        assert author_edits.SESSION_KEY not in client.session


class TestDeleteEndpoint:
    pytestmark = pytest.mark.django_db

    def test_owner_can_soft_delete(self, client, comment, feature_on):
        from django.urls import reverse

        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-delete-comment-ajax"),
            {"comment_id": str(comment.pk)},
            **AJAX,
        )
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert isinstance(r.json()["comment_id"], str)
        comment.refresh_from_db()
        assert comment.is_removed is True
        assert comment.is_public is False
        assert str(comment.pk) in author_edits.deleted_comment_pks()

    def test_non_owner_cannot_delete(self, client, comment, feature_on):
        from django.urls import reverse

        r = client.post(
            reverse("comments-delete-comment-ajax"),
            {"comment_id": str(comment.pk)},
            **AJAX,
        )
        assert r.status_code == 403
        comment.refresh_from_db()
        assert comment.is_removed is False

    def test_answered_comment_cannot_be_deleted(self, client, comment, post, settings, feature_on):
        from django.urls import reverse
        from django_comments import get_model as get_comments_model

        reply = get_comments_model()(content_object=post, site_id=settings.SITE_ID, comment="reply", parent=comment)
        reply.save()
        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-delete-comment-ajax"),
            {"comment_id": str(comment.pk)},
            **AJAX,
        )
        assert r.status_code == 403
        comment.refresh_from_db()
        assert comment.is_removed is False

    def test_already_removed_comment_cannot_be_deleted(self, client, comment, feature_on):
        # Preserves moderation evidence: an author cannot erase a removed comment.
        from django.urls import reverse

        comment.is_removed = True
        comment.is_public = False
        comment.save()
        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-delete-comment-ajax"),
            {"comment_id": str(comment.pk)},
            **AJAX,
        )
        assert r.status_code == 403
        assert str(comment.pk) not in author_edits.deleted_comment_pks()

    def test_feature_disabled_returns_404(self, client, comment, settings):
        from django.urls import reverse

        settings.CAST_COMMENTS_ALLOW_AUTHOR_EDITS = False
        seed_ownership(client, comment)
        r = client.post(
            reverse("comments-delete-comment-ajax"),
            {"comment_id": str(comment.pk)},
            **AJAX,
        )
        assert r.status_code == 404
