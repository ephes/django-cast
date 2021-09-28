from django.urls import include, re_path

from wagtail.admin import urls as wagtailadmin_urls
from wagtail.core import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from rest_framework.documentation import include_docs_urls


urlpatterns = [
    # allauth
    re_path(r"^accounts/", include("allauth.urls")),
    # rest framework docs/schema urls
    re_path(r"^docs/", include_docs_urls(title="cast API service")),
    re_path(r"^cast/", include("cast.urls", namespace="cast")),
    # comments
    re_path(r"^posts/comments/", include("fluent_comments.urls")),
    # wagtail
    re_path(r"^cms/", include(wagtailadmin_urls)),
    re_path(r"^documents/", include(wagtaildocs_urls)),
    re_path(r"", include(wagtail_urls)),  # default is wagtail
]
