from __future__ import unicode_literals, absolute_import

from django.conf.urls import url, include
from rest_framework.documentation import include_docs_urls


urlpatterns = [
    # allauth
    url(r"^accounts/", include("allauth.urls")),
    # CKEditor upload
    url(r"^ckeditor/", include("ckeditor_uploader.urls")),
    # rest framework docs/schema urls
    url(r"^docs/", include_docs_urls(title="cast API service")),
    url(r"^", include("cast.urls", namespace="cast")),
    # comments
    url(r"^posts/comments/", include("fluent_comments.urls")),
]
