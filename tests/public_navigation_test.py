import pytest
from wagtail.models import PageViewRestriction

from cast.models.repository import BlogIndexContext, FeedContext, PostDetailContext, data_for_blog_cachable
from tests.factories import BlogFactory


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
