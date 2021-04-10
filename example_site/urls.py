from django.urls import path
from django.urls import re_path
from django.contrib import admin
from django.conf import settings
from django.contrib import admin
from django.conf.urls import include, url, re_path
from django.views.generic import TemplateView
from django.views.generic import RedirectView

from rest_framework.documentation import include_docs_urls
from rest_framework.authtoken import views as authtokenviews


urlpatterns = [
    # path("", RedirectView.as_view(url="/about"), name="home"),
    path(
        "about/", TemplateView.as_view(template_name="pages/about.html"), name="about",
    ),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # Cast
    url(r"^api/api-token-auth/", authtokenviews.obtain_auth_token),
    url(r"^api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    url(r"^docs/", include_docs_urls(title="My Blog API service")),
    path("ckeditor/", include("ckeditor_uploader.urls")),
    # Uploads
    path("uploads/", include("filepond.urls", namespace="filepond")),
    # Cast
    # path("cast/", include("cast.urls", namespace="cast")),
    # Threadedcomments
    re_path(r"^show/comments/", include("fluent_comments.urls")),
]


if settings.DEBUG:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    # Serve static and media files from development server
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
