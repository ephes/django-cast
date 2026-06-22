from __future__ import annotations

from django.urls import include, path
import django_comments.urls

from . import views

urlpatterns = [
    path("post/ajax/", views.post_comment_ajax, name="comments-post-comment-ajax"),
    path("edit/ajax/", views.post_comment_edit_ajax, name="comments-edit-comment-ajax"),
    path("delete/ajax/", views.post_comment_delete_ajax, name="comments-delete-comment-ajax"),
    # Override the stock post view (defined before the include so it wins) to
    # coordinate threaded replies with the author-edits feature.
    path("post/", views.post_comment, name="comments-post-comment"),
    path("", include(django_comments.urls)),
]
