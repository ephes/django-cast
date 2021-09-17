from django.conf.urls import include, re_path, url

from wagtail.admin import urls as wagtailadmin_urls
from wagtail.core import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from rest_framework.documentation import include_docs_urls


urlpatterns = [
    # allauth
    url(r"^accounts/", include("allauth.urls")),
    # CKEditor upload
    url(r"^ckeditor/", include("ckeditor_uploader.urls")),
    # rest framework docs/schema urls
    url(r"^docs/", include_docs_urls(title="cast API service")),
    url(r"^cast/", include("cast.urls", namespace="cast")),
    # comments
    url(r"^posts/comments/", include("fluent_comments.urls")),
    # wagtail
    url(r"^cms/", include(wagtailadmin_urls)),
    url(r"^documents/", include(wagtaildocs_urls)),
    re_path(r"", include(wagtail_urls)),  # default is wagtail
]
