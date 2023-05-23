from unittest.mock import patch

import pytest
from django.urls import reverse
from django_comments import get_model as get_comments_model
from django_comments import signals
from django_comments.forms import CommentForm

from cast.moderation import Moderator


class TestPostComments:
    pytestmark = pytest.mark.django_db

    def test_comment_form_not_included(self, client, post, comments_not_enabled):
        detail_url = post.get_url()
        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert post.title in content
        assert "form" not in r.context

    def test_comment_form_included(self, client, post, comments_enabled):
        detail_url = post.get_url()
        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert post.title in content
        assert isinstance(r.context["form"], CommentForm)

    def test_comment_in_comment_list(self, client, post, comment, comments_enabled):
        detail_url = post.get_url()
        r = client.get(detail_url)
        assert r.status_code == 200

        assert comment in r.context["comment_list"]

    def test_add_new_comment(self, client, post, comments_enabled):
        ajax_url = reverse("comments-post-comment-ajax")
        detail_url = post.get_url()

        r = client.get(detail_url)
        content = r.content.decode("utf-8")
        security_hash, timestamp = None, None
        for line in content.split("\n"):
            if "security_hash" in line:
                for part in line.split("input"):
                    if "security_hash" in part:
                        for attr in part.split(" "):
                            if "value" in attr:
                                security_hash = attr.split('"')[1]
                    if "timestamp" in part:
                        for attr in part.split():
                            if "value" in attr:
                                timestamp = attr.split('"')[1]

        data = {
            "content_type": "cast.post",
            "object_pk": str(post.pk),
            "comment": "new content",
            "name": "Name",
            "email": "fuz@baz.com",
            "title": "buzz",
            "security_hash": security_hash,
            "timestamp": timestamp,
        }

        r = client.post(ajax_url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        assert r.status_code == 200

        rdata = r.json()
        assert rdata["success"]

        comment = get_comments_model().objects.get(pk=rdata["comment_id"])
        assert comment.comment == data["comment"]


class TestCommentModeration:
    @classmethod
    def setup_class(cls):
        class Stub:
            pass

        class StubComment:
            name = "name"
            email = "foo@example.com"
            title = "foobar title"
            comment = "some comment"
            is_removed = False
            is_public = True

        class PredictSpam:
            @staticmethod
            def predict_label(_):
                return "spam"

        class PredictHam:
            @staticmethod
            def predict_label(_):
                return "ham"

        class SpamFilter:
            def __init__(self, model):
                self.model = model

        cls.post = post = Stub()
        cls.stub_class = Stub
        cls.comment_class = StubComment
        cls.comment = comment = StubComment()
        comment.content_object = post
        cls.request = Stub()
        cls.predict_spam = SpamFilter(PredictSpam())
        cls.predict_ham = SpamFilter(PredictHam())

    @pytest.mark.django_db
    def test_spamfilter_is_none(self):
        with patch("fluent_comments.receivers.default_moderator", new=Moderator(self.stub_class, spamfilter=None)):
            signals.comment_will_be_posted.send(sender=self.comment_class, comment=self.comment, request=self.request)
            assert self.comment.is_public
            assert not self.comment.is_removed

    def test_moderated_comment_marked_is_removed(self):
        with patch(
            "fluent_comments.receivers.default_moderator", new=Moderator(self.stub_class, spamfilter=self.predict_spam)
        ):
            signals.comment_will_be_posted.send(sender=self.comment_class, comment=self.comment, request=self.request)
            assert self.comment.is_removed
            assert not self.comment.is_public

    def test_moderated_comment_is_not_marked_is_removed(self):
        with patch(
            "fluent_comments.receivers.default_moderator", new=Moderator(self.stub_class, spamfilter=self.predict_ham)
        ):
            signals.comment_will_be_posted.send(sender=self.comment_class, comment=self.comment, request=self.request)
            assert self.comment.is_public
            assert not self.comment.is_removed
