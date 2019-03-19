import pytest
from django.urls import reverse

from cast.models import Post


class TestPostAdd:
    pytestmark = pytest.mark.django_db

    def test_get_post_add_not_authenticated(self, client, blog):
        create_url = reverse("cast:post_create", kwargs={"slug": blog.slug})

        r = client.get(create_url)
        # redirect to login
        assert r.status_code == 302

    def test_get_post_add_authenticated(self, client, blog):
        create_url = reverse("cast:post_create", kwargs={"slug": blog.slug})
        r = client.login(username=blog.user.username, password=blog.user._password)
        r = client.get(create_url)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        assert "ckeditor" in content

    def test_post_create_not_authenticated(self, client, blog):
        create_url = reverse("cast:post_create", kwargs={"slug": blog.slug})
        data = {
            "title": "test title",
            "content": "foo bar baz",
            "published": True,
            "keywords": "",
            "podcast_audio": "",
            "explicit": "2",    # 2 -> no
            "block": False,
            "slug": "blog-slug",
        }
        r = client.post(create_url, data, follow=True)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "Sign In" in content

    def test_post_create_authenticated(self, client, blog):
        user = blog.user
        r = client.login(username=user.username, password=user._password)

        create_url = reverse("cast:post_create", kwargs={"slug": blog.slug})
        data = {
            "title": "test title",
            "content": "foo bar baz",
            "published": True,
            "keywords": "",
            "podcast_audio": "",
            "explicit": "2",    # 2 -> no
            "block": False,
            "slug": "blog-slug",
        }
        r = client.post(create_url, data)
        print(r.content)
        assert r.status_code == 302
        assert Post.objects.get(slug=data["slug"]).title == data["title"]

    def test_post_create_authenticated_with_image(self, client, blog, image):
        user = blog.user

        r = client.login(username=user.username, password=user._password)

        content = "with image: {{% image {} %}}".format(image.pk)
        create_url = reverse("cast:post_create", kwargs={"slug": blog.slug})
        data = {
            "title": "test title",
            "content": content,
            "published": True,
            "keywords": "",
            "podcast_audio": "",
            "explicit": "2",    # 2 -> no
            "block": False,
            "slug": "blog-slug",
        }
        r = client.post(create_url, data)
        assert r.status_code == 302
        bp = Post.objects.get(slug=data["slug"])
        bis = list(bp.images.all())
        assert bp.title == data["title"]
        assert len(bis) == 1
        assert bis[0].pk == image.pk

    def test_post_create_authenticated_with_video(self, client, blog, video):
        user = video.user
        r = client.login(username=user.username, password=user._password)

        content = "with video: {{% video {} %}}".format(video.pk)
        create_url = reverse("cast:post_create", kwargs={"slug": blog.slug})
        data = {
            "title": "test title",
            "content": content,
            "published": True,
            "keywords": "",
            "podcast_audio": "",
            "explicit": "2",    # 2 -> no
            "block": False,
            "slug": "blog-slug",
        }
        r = client.post(create_url, data)
        assert r.status_code == 302
        bp = Post.objects.get(slug=data["slug"])
        bvs = list(bp.videos.all())
        assert bp.title == data["title"]
        assert len(bvs) == 1
        assert bvs[0].pk == video.pk

    def test_post_create_authenticated_with_gallery(self, client, blog, gallery):
        user = gallery.user
        r = client.login(username=user.username, password="password")

        content = "with gallery: {{% gallery {} %}}".format(gallery.pk)
        create_url = reverse("cast:post_create", kwargs={"slug": blog.slug})
        data = {
            "title": "test title",
            "content": content,
            "published": True,
            "keywords": "",
            "podcast_audio": "",
            "explicit": "2",    # 2 -> no
            "block": False,
            "slug": "blog-slug",
        }
        r = client.post(create_url, data)
        assert r.status_code == 302
        bp = Post.objects.get(slug=data["slug"])
        bgs = list(bp.galleries.all())
        assert bp.title == data["title"]
        assert len(bgs) == 1
        assert bgs[0].pk == gallery.pk
        assert len(gallery.images.all()) == 1
