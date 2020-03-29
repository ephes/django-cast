from django.urls import path
from django.urls import re_path
from django.contrib import admin
from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin

from wagtail.admin import urls as wagtailadmin_urls
from wagtail.core import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from rest_framework.documentation import include_docs_urls
from rest_framework.authtoken import views as authtokenviews


urlpatterns = [
    url(r"^django-admin/", admin.site.urls),
    url(r"^admin/", include(wagtailadmin_urls)),
    url(r"^documents/", include(wagtaildocs_urls)),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # Cast
    path("api/api-token-auth/", authtokenviews.obtain_auth_token),
    path("docs/", include_docs_urls(title="API service")),
    path("ckeditor/", include("ckeditor_uploader.urls")),
    # Uploads
    path("uploads/", include("filepond.urls", namespace="filepond")),
    # Cast
    path("cast/", include("cast.urls", namespace="cast")),
    # Threadedcomments
    re_path(r"^show/comments/", include("fluent_comments.urls")),
    # Wagtail
    url(r"^pages/", include(wagtail_urls)),
]


if settings.DEBUG:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    # Serve static and media files from development server
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
