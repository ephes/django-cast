import django_comments.urls
from django.conf.urls import include, url

from . import views

urlpatterns = [
    url(r"^post/ajax/$", views.post_comment_ajax, name="comments-post-comment-ajax"),
    url(r"", include(django_comments.urls)),
]
