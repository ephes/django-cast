from __future__ import annotations

import django_comments.urls
from django.urls import include, path, re_path

from . import views

urlpatterns = [
    path("post/ajax/", views.post_comment_ajax, name="comments-post-comment-ajax"),
    path("edit/ajax/", views.post_comment_edit_ajax, name="comments-edit-comment-ajax"),
    path("delete/ajax/", views.post_comment_delete_ajax, name="comments-delete-comment-ajax"),
    # Override the stock post view (defined before the include so it wins) to
    # coordinate threaded replies with the author-edits feature.
    path("post/", views.post_comment, name="comments-post-comment"),
    # Override the stock ``comments-url-redirect`` (Django's contenttypes
    # shortcut), which redirects to any object's URL without permission checks.
    # ``Comment.get_absolute_url()`` reverses this name, so keep it.
    re_path(r"^cr/(\d+)/(.+)/$", views.comment_target_redirect, name="comments-url-redirect"),
    path("", include(django_comments.urls)),
]
