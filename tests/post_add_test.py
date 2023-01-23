import pytest
from django.urls import reverse

from cast.models import Post


class TestPostAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_form_post_not_authenticated(self, client, blog):
        add_url = reverse("wagtailadmin_pages:add_subpage", args=(blog.id,))
        r = client.get(add_url)

        # redirect to log in
        assert r.status_code == 302
        login_url = reverse("wagtailadmin_login")
        assert login_url in r.url

    def test_get_add_form_post_authenticated(self, client, blog):
        add_url = reverse("wagtailadmin_pages:add_subpage", args=(blog.id,))
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        r = client.get(add_url, follow=True)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        # make sure we got the wagtail add subpage form and not the login form
        assert '<body id="wagtail" class="  ">' in content

    def test_submit_add_form_post_not_authenticated(self, client, post_data_wagtail, blog):
        add_url = reverse("wagtailadmin_pages:add", args=("cast", "post", blog.id))
        r = client.post(add_url, post_data_wagtail)

        # make sure we are redirected to login page
        assert r.status_code == 302
        login_url = reverse("wagtailadmin_login")
        assert login_url in r.url

    def test_submit_add_form_post_authenticated(self, client, post_data_wagtail, blog):
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        add_url = reverse("wagtailadmin_pages:add", args=("cast", "post", blog.id))
        r = client.post(add_url, post_data_wagtail)

        # make sure we are redirected to blog index
        assert r.status_code == 302
        assert r.url == reverse("wagtailadmin_explore", args=(blog.id,))

        # make sure there was a post added to the database
        assert Post.objects.get(slug=post_data_wagtail["slug"]).title == post_data_wagtail["title"]

    def test_submit_add_form_post_authenticated_with_image(self, client, post_data_wagtail, blog, image):
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        add_url = reverse("wagtailadmin_pages:add", args=("cast", "post", blog.id))
        post_data_wagtail["body-0-value-0-type"] = "image"
        post_data_wagtail["body-0-value-0-value"] = image.id

        r = client.post(add_url, post_data_wagtail)

        # make sure we are redirected to blog index
        assert r.status_code == 302
        assert r.url == reverse("wagtailadmin_explore", args=(blog.id,))

        post = Post.objects.get(slug=post_data_wagtail["slug"])

        # make sure there was a post added to the database
        assert post.title == post_data_wagtail["title"]

        # make sure there was an image added
        assert post.images.count() == 1
        assert post.images.first() == image

    def test_submit_add_form_post_authenticated_with_video(self, client, post_data_wagtail, blog, video):
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        add_url = reverse("wagtailadmin_pages:add", args=("cast", "post", blog.id))
        post_data_wagtail["body-0-value-0-type"] = "video"
        post_data_wagtail["body-0-value-0-value"] = video.id

        r = client.post(add_url, post_data_wagtail)

        # make sure we are redirected to blog index
        assert r.status_code == 302
        assert r.url == reverse("wagtailadmin_explore", args=(blog.id,))

        post = Post.objects.get(slug=post_data_wagtail["slug"])

        # make sure there was a post added to the database
        assert post.title == post_data_wagtail["title"]

        # make sure there was a video added
        assert post.videos.count() == 1
        assert post.videos.first() == video

    def test_submit_add_form_post_authenticated_with_gallery(self, client, post_data_wagtail, blog, gallery):
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        add_url = reverse("wagtailadmin_pages:add", args=("cast", "post", blog.id))

        post_data_wagtail["body-0-value-0-type"] = "gallery"
        post_data_wagtail["body-0-value-0-value-0-id"] = ""
        post_data_wagtail["body-0-value-0-value-count"] = gallery.images.count()
        post_data_wagtail["body-0-value-0-value-0-value"] = gallery.images.first().pk
        post_data_wagtail["body-0-value-0-value-0-deleted"] = ""
        post_data_wagtail["body-0-value-0-value-0-order"] = "0"

        r = client.post(add_url, post_data_wagtail)

        # make sure we are redirected to blog index
        assert r.status_code == 302
        assert r.url == reverse("wagtailadmin_explore", args=(blog.id,))

        post = Post.objects.get(slug=post_data_wagtail["slug"])

        # make sure there was a post added to the database
        assert post.title == post_data_wagtail["title"]

        # make sure there was a gallery added
        assert post.galleries.count() == 1
        assert post.galleries.first() == gallery
        assert list(post.galleries.first().images.all()) == list(gallery.images.all())

    def test_submit_add_form_post_authenticated_with_code(self, client, post_data_wagtail, blog, video):
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        add_url = reverse("wagtailadmin_pages:add", args=("cast", "post", blog.id))
        post_data_wagtail["body-0-value-0-type"] = "code"
        post_data_wagtail["body-0-value-0-value-language"] = "python"
        post_data_wagtail["body-0-value-0-value-source"] = 'def hello_world():\n    print("Hello World!")'

        r = client.post(add_url, post_data_wagtail)

        # make sure we are redirected to blog index
        assert r.status_code == 302
        assert r.url == reverse("wagtailadmin_explore", args=(blog.id,))

        post = Post.objects.get(slug=post_data_wagtail["slug"])

        # make sure there was a post added to the database
        assert post.title == post_data_wagtail["title"]

        # make sure there was a code block added
        assert post.body.raw_data[0]["value"][0]["value"]["language"] == "python"
        assert "hello_world" in post.body.raw_data[0]["value"][0]["value"]["source"]
        assert "highlight" in str(post.body)
