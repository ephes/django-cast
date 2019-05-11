import pytest
<<<<<<< HEAD

from django.urls import reverse

from django_comments import get_model as get_comments_model


class TestPostComments:
    pytestmark = pytest.mark.django_db

    def test_comment_form_not_included(self, client, post, comments_not_enabled):
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert post.title in content
        assert "comment" not in content

    def test_comment_form_included(self, client, post, comments_enabled):
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert post.title in content
        assert "comment" in content

    def test_comment_in_comment_list(self, client, post, comment, comments_enabled):
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.get(detail_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert str(comment.comment) in content

    def test_add_new_comment(self, client, post, comments_enabled):
        ajax_url = reverse("comments-post-comment-ajax")
        slugs = {"blog_slug": post.blog.slug, "slug": post.slug}
        detail_url = reverse("cast:post_detail", kwargs=slugs)

        r = client.get(detail_url)
        content = r.content.decode("utf-8")
        for line in content.split("\n"):
            if "security_hash" in line:
                for part in line.split("input"):
                    if "security_hash" in part:
                        for attr in part.split(' '):
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

        comment = get_comments_model().objects.get(pk=rdata["object_id"])
        assert comment.comment == data["comment"]
