from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

# from rest_framework.authtoken import views as authtokenviews  # TODO: Python 3.13 compatibility issue with coreapi
# from rest_framework.documentation import include_docs_urls  # TODO: Python 3.13 compatibility with coreapi
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.api.v2.views import PagesAPIViewSet
from wagtail.documents import urls as wagtaildocs_urls

# openapi endpoint broken until this is fixed:
# https://github.com/wagtail/wagtail/issues/8583
PagesAPIViewSet.schema = None


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
    # path("api/api-token-auth/", authtokenviews.obtain_auth_token, name="api-token-auth"),  # TODO: Python 3.13 compatibility
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
    # path("docs/", include_docs_urls(title="My Blog API service")),  # TODO: Python 3.13 compatibility with coreapi
    # Cast
    path("cast/", include("cast.urls", namespace="cast")),
    # Comments
    path("show/comments/", include("cast.comments.urls")),
    # Wagtail
    path(settings.WAGTAILADMIN_BASE_URL, include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("", include(wagtail_urls)),  # default is wagtail
]


if settings.DEBUG:
    from django.conf.urls.static import static
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    # Serve static and media files from development server
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
