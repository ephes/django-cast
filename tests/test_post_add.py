import pytest

from django.urls import reverse

from wagtail.images.models import Image

from cast.models import Post


class TestPostAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_form_post_not_authenticated(self, client, blog):
        add_url = reverse("wagtailadmin_pages:add_subpage", args=(blog.id,))
        r = client.get(add_url)

        # redirect to login
        assert r.status_code == 302

    def test_get_add_form_post_authenticated(self, client, blog):
        add_url = reverse("wagtailadmin_pages:add_subpage", args=(blog.id,))
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        r = client.get(add_url, follow=True)
        assert r.status_code == 200

        content = r.content.decode("utf-8")
        assert "html" in content
        # make sure we got the wagtail add subpage form and not the login form
        assert '<body id="wagtail" class="  focus-outline-on">' in content

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

    def test_submit_add_form_post_authenticated_with_image(self, client, post_data_wagtail, blog, wagtail_image):
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        add_url = reverse("wagtailadmin_pages:add", args=("cast", "post", blog.id))
        post_data_wagtail["body-0-value-0-type"] = "image"
        post_data_wagtail["body-0-value-0-value"] = wagtail_image.id

        r = client.post(add_url, post_data_wagtail)

        # make sure we are redirected to blog index
        assert r.status_code == 302
        assert r.url == reverse("wagtailadmin_explore", args=(blog.id,))

        post = Post.objects.get(slug=post_data_wagtail["slug"])

        # make sure there was a post added to the database
        assert post.title == post_data_wagtail["title"]

        # make sure there was an image added
        assert post.images.count() == 1
        assert post.images.first() == wagtail_image

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

        # make sure there was an video added
        assert post.videos.count() == 1
        assert post.videos.first() == video
    
    def test_submit_add_form_post_authenticated_with_gallery(self, client, post_data_wagtail, blog, gallery):
        _ = client.login(username=blog.owner.username, password=blog.owner._password)
        add_url = reverse("wagtailadmin_pages:add", args=("cast", "post", blog.id))
        post_data_wagtail["body-0-value-0-type"] = "gallery"
        post_data_wagtail["body-0-value-0-value"] = gallery.id

        r = client.post(add_url, post_data_wagtail)

        # make sure we are redirected to blog index
        assert r.status_code == 302
        assert r.url == reverse("wagtailadmin_explore", args=(blog.id,))

        post = Post.objects.get(slug=post_data_wagtail["slug"])

        # make sure there was a post added to the database
        assert post.title == post_data_wagtail["title"]

        # make sure there was an gallery added
        assert post.galleries.count() == 1
        assert post.galleries.first() == gallery

    # FIXME test post with media in content -> db link between media and post later
    # def test_post_create_authenticated_with_gallery(self, client, blog, gallery):
    #     user = gallery.user
    #     r = client.login(username=user.username, password="password")

    #     content = "with gallery: {{% gallery {} %}}".format(gallery.pk)
    #     create_url = reverse("cast:post_create", kwargs={"slug": blog.slug})
    #     data = {
    #         "title": "test title",
    #         "content": content,
    #         "published": True,
    #         "keywords": "",
    #         "podcast_audio": "",
    #         "explicit": "2",  # 2 -> no
    #         "block": False,
    #         "slug": "blog-slug",
    #     }
    #     r = client.post(create_url, data)
    #     assert r.status_code == 302
    #     bp = Post.objects.get(slug=data["slug"])
    #     bgs = list(bp.galleries.all())
    #     assert bp.title == data["title"]
    #     assert len(bgs) == 1
    #     assert bgs[0].pk == gallery.pk
    #     assert len(gallery.images.all()) == 1
