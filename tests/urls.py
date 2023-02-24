from django.urls import include, path, re_path
from rest_framework.documentation import include_docs_urls
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

urlpatterns = [
    # allauth
    path("accounts/", include("allauth.urls")),
    # rest framework docs/schema urls
    re_path(r"^docs/", include_docs_urls(title="cast API service")),
    path("cast/", include("cast.urls", namespace="cast")),
    # comments
    path("posts/comments/", include("fluent_comments.urls")),
    # wagtail
    path("cms/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("", include(wagtail_urls)),  # default is wagtail
]
