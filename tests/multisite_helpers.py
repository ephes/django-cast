from wagtail.models import Page, Site

from .factories import HomePageFactory


def create_site_root(*, owner, hostname: str, slug: str, title: str) -> tuple[Site, object]:
    root_page = Page.get_first_root_node()
    assert root_page is not None
    home_page = HomePageFactory(owner=owner, title=title, slug=slug, parent=root_page)
    site = Site.objects.create(hostname=hostname, port=80, root_page=home_page, is_default_site=False)
    return site, home_page
