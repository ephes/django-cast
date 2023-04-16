from django.urls import include, path, re_path
from rest_framework.documentation import include_docs_urls
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from cast.views import defaults as default_views_cast

handler404 = default_views_cast.page_not_found
handler500 = default_views_cast.server_error
handler400 = default_views_cast.bad_request
handler403 = default_views_cast.permission_denied


urlpatterns = [
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
