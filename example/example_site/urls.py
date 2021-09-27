from django.conf import settings
from django.conf.urls import include, re_path, url
from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView

from wagtail.admin import urls as wagtailadmin_urls
from wagtail.core import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from rest_framework.authtoken import views as authtokenviews
from rest_framework.documentation import include_docs_urls


urlpatterns = [
    # path("", RedirectView.as_view(url="/about"), name="home"),
    path(
        "about/",
        TemplateView.as_view(template_name="pages/about.html"),
        name="about",
    ),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # Cast
    url(r"^api/api-token-auth/", authtokenviews.obtain_auth_token),
    url(r"^api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    url(r"^docs/", include_docs_urls(title="My Blog API service")),
    path("ckeditor/", include("ckeditor_uploader.urls")),
    # Cast
    path("cast/", include("cast.urls", namespace="cast")),
    # Threadedcomments
    re_path(r"^show/comments/", include("fluent_comments.urls")),
    # Wagtail
    url(r"^cms/", include(wagtailadmin_urls)),
    url(r"^documents/", include(wagtaildocs_urls)),
    re_path(r"", include(wagtail_urls)),  # default is wagtail
]


if settings.DEBUG:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    # Serve static and media files from development server
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
