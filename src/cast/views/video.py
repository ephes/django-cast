from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from modelsearch.backends.base import BaseSearchResults
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy

from ..forms import get_video_form
from ..models import Video
from ..search_utils import normalize_modelsearch_query, safe_modelsearch_results
from . import AuthenticatedHttpRequest
from .media import MediaAdminConfig, MediaAdminViews

video_permission_policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")


def get_video_data(video: Video) -> dict[str, Any]:
    """
    helper function: given a video, return the json to pass back to the
    chooser panel - move to model FIXME
    """
    return {
        "id": video.id,
        "title": video.title,
        "edit_link": reverse("castvideo:edit", args=(video.id,)),
    }


def _search_video(base_videos: Any, raw_query_string: str) -> tuple[Any | BaseSearchResults, str | None]:
    return safe_modelsearch_results(base_videos, raw_query_string), normalize_modelsearch_query(
        raw_query_string
    ) or None


def _delete_old_video_files(video_id: int, form: Any) -> None:
    old_video = get_object_or_404(Video, id=video_id)
    if "original" in form.changed_data and old_video.original.name:
        old_video.original.storage.delete(old_video.original.name)


def _create_video(user: Any) -> Video:
    return Video(user=user)


def _video_message_arg(video: Video) -> Any:
    return video.title


def _video_file_for_size(video: Video) -> Any:
    return video.original


def _extra_video_edit_context(request: HttpRequest, video: Video) -> dict[str, Any]:
    return {}


video_admin_config = MediaAdminConfig(
    model=Video,
    permission_policy=video_permission_policy,
    get_form=get_video_form,
    url_namespace="castvideo",
    template_dir="cast/video",
    plural_context_name="videos",
    singular_context_name="video",
    chosen_step="video_chosen",
    get_chosen_data=get_video_data,
    create_instance=_create_video,
    search=_search_video,
    ordering="-created",
    show_popular_tags=True,
    index_search_placeholder=_("Search video files"),
    index_fallback_placeholder=_("Search media"),
    added_message=_("Video file '{0}' added."),
    add_error_message=_("The video file could not be saved due to errors."),
    updated_message=_("Video file '{0}' updated"),
    update_error_message=_("The media could not be saved due to errors."),
    deleted_message=_("Video '{0}' deleted."),
    chooser_upload_error_message=_("The video could not be saved due to errors."),
    file_missing_message=_("The file could not be found. Please change the source or delete the video file"),
    message_arg=_video_message_arg,
    edit_form_initial=None,
    delete_old_files=_delete_old_video_files,
    get_file_for_size=_video_file_for_size,
    extra_edit_context=_extra_video_edit_context,
)

_views = MediaAdminViews(video_admin_config)

index = _views.index
chooser = _views.chooser


def add(request: AuthenticatedHttpRequest) -> HttpResponse:
    return _views.add(request)


def edit(request: HttpRequest, video_id: int) -> HttpResponse:
    return _views.edit(request, video_id)


def delete(request: HttpRequest, video_id: int) -> HttpResponse:
    return _views.delete(request, video_id)


def chosen(request: HttpRequest, video_id: int) -> HttpResponse:
    return _views.chosen(request, video_id)


def chooser_upload(request: AuthenticatedHttpRequest) -> HttpResponse:
    return _views.chooser_upload(request)
