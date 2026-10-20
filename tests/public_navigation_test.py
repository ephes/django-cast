import pytest
from django.test import override_settings
from wagtail.models import Page, PageViewRestriction, Site

from cast.models.repository import BlogIndexContext, FeedContext, PostDetailContext, data_for_blog_cachable
from tests.factories import BlogFactory, HomePageFactory, PostFactory
from tests.multisite_helpers import create_site_root


@pytest.mark.django_db
@pytest.mark.parametrize(
    "restriction", [PageViewRestriction.LOGIN, PageViewRestriction.PASSWORD, PageViewRestriction.GROUPS]
)
@pytest.mark.parametrize("restricted_root", [False, True])
@pytest.mark.parametrize("builder", ["cached", "blog", "post", "feed"])
def test_root_navigation_only_contains_public_pages(rf, post, site, builder, restriction, restricted_root):
    public = BlogFactory(parent=site.root_page, title="Public navigation", slug="public-nav")
    private = BlogFactory(parent=site.root_page, title="Restricted navigation", slug="private-nav")
    PageViewRestriction.objects.create(
        page=site.root_page if restricted_root else private, restriction_type=restriction, password="secret"
    )
    request = rf.get(post.url)
    if builder == "cached":
        links = data_for_blog_cachable(request=request, blog=post.blog)["root_nav_links"]
    elif builder == "blog":
        links = BlogIndexContext.create_from_django_models(request, post.blog).root_nav_links
    elif builder == "post":
        links = PostDetailContext.create_from_django_models(request, post).root_nav_links
    else:
        links = FeedContext.create_from_django_models(
            request=request, blog=post.blog, post_queryset=post.blog.unfiltered_published_posts
        ).root_nav_links
    if restricted_root:
        assert links == []
    else:
        assert (public.get_url(), public.title) in links
    assert all(title != private.title and url != private.get_url() for url, title in links)


def _root_nav_links(builder, request, post):
    if builder == "cached":
        return data_for_blog_cachable(request=request, blog=post.blog)["root_nav_links"]
    if builder == "blog":
        return BlogIndexContext.create_from_django_models(request, post.blog).root_nav_links
    if builder == "post":
        return PostDetailContext.create_from_django_models(request, post).root_nav_links
    return FeedContext.create_from_django_models(
        request=request, blog=post.blog, post_queryset=post.blog.unfiltered_published_posts
    ).root_nav_links


@pytest.mark.django_db
@pytest.mark.parametrize("builder", ["cached", "blog", "post", "feed"])
def test_root_navigation_uses_site_root_below_tree_root(rf, user, site, body, builder):
    # The usual Wagtail tree: the site's root page is a home page below the page tree root.
    home = HomePageFactory(owner=user, title="Home", slug="nav-home", parent=Page.get_first_root_node())
    site.root_page = home
    site.save()
    blog = BlogFactory(owner=user, title="Nav Blog", slug="nav-blog", parent=home)
    BlogFactory(owner=user, title="Nav About", slug="nav-about", parent=home)
    post = PostFactory(owner=user, title="Nav Post", slug="nav-post", body=body, parent=blog)

    titles = [title for _url, title in _root_nav_links(builder, rf.get(post.url), post)]

    assert titles == ["Nav Blog", "Nav About"]


@pytest.mark.django_db
@pytest.mark.parametrize("builder", ["cached", "blog", "post", "feed"])
def test_root_navigation_uses_the_requested_site(rf, user, body, builder):
    _site1, site1_root = create_site_root(owner=user, hostname="nav-site1.local", slug="nav-site1", title="Site 1")
    site2, site2_root = create_site_root(owner=user, hostname="nav-site2.local", slug="nav-site2", title="Site 2")
    BlogFactory(owner=user, title="Site 1 Blog", slug="site-1-blog", parent=site1_root)
    blog = BlogFactory(owner=user, title="Site 2 Blog", slug="site-2-blog", parent=site2_root)
    BlogFactory(owner=user, title="Site 2 About", slug="site-2-about", parent=site2_root)
    post = PostFactory(owner=user, title="Site 2 Post", slug="site-2-post", body=body, parent=blog)

    with override_settings(ALLOWED_HOSTS=["testserver", "nav-site1.local", site2.hostname]):
        request = rf.get(post.url, HTTP_HOST=site2.hostname)
        titles = [title for _url, title in _root_nav_links(builder, request, post)]

    assert titles == ["Site 2 Blog", "Site 2 About"]


@pytest.mark.django_db
def test_post_detail_root_navigation_without_site(rf, post):
    # A theme chosen on the blog avoids the per-site theme setting, which needs a site.
    post.blog.template_base_dir = "bootstrap4"
    post.blog.save()
    request = rf.get(post.url)
    Site.objects.all().delete()

    assert PostDetailContext.create_from_django_models(request, post).root_nav_links == []
