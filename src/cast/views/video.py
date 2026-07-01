from typing import Any, cast

from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers
from modelsearch.backends.base import BaseSearchResults
from wagtail.admin import messages
from wagtail.admin.modal_workflow import render_modal_workflow
from wagtail.admin.models import popular_tags_for_model
from wagtail.permission_policies.collections import CollectionOwnershipPermissionPolicy
from wagtail.search.backends import get_search_backends

from ..appsettings import CHOOSER_PAGINATION, MENU_ITEM_PAGINATION
from ..forms import NonEmptySearchForm, get_video_form
from ..models import Video
from ..search_utils import normalize_modelsearch_query, safe_modelsearch_results
from . import AuthenticatedHttpRequest
from .wagtail_pagination import paginate, pagination_template

video_permission_policy = CollectionOwnershipPermissionPolicy(Video, auth_model=Video, owner_field_name="user")


@vary_on_headers("X-Requested-With")
def index(request: HttpRequest) -> HttpResponse:
    ordering = "-created"
    user_can_add = video_permission_policy.user_has_permission(request.user, "add")
    base_videos = video_permission_policy.instances_user_has_any_permission_for(
        request.user, ["change", "delete"]
    ).order_by(ordering)
    if not user_can_add and not base_videos.exists():
        raise PermissionDenied
    videos: models.QuerySet | BaseSearchResults = base_videos

    # Search
    query_string = None
    if "q" in request.GET:
        form = NonEmptySearchForm(request.GET, placeholder=_("Search video files"))
        if form.is_valid():
            raw_query_string = form.cleaned_data["q"]
            videos = safe_modelsearch_results(base_videos, raw_query_string)
            query_string = normalize_modelsearch_query(raw_query_string) or None
    else:
        form = NonEmptySearchForm(placeholder=_("Search media"))

    # Pagination
    paginator, video_items = paginate(request, videos, per_page=MENU_ITEM_PAGINATION)

    # Create response
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(
            request,
            "cast/video/results.html",
            {
                "ordering": ordering,
                "videos": video_items,
                "query_string": query_string,
                "is_searching": bool(query_string),
            },
        )
    else:
        return render(
            request,
            "cast/video/index.html",
            {
                "ordering": ordering,
                "videos": video_items,
                "query_string": query_string,
                "is_searching": bool(query_string),
                "search_form": form,
                "popular_tags": popular_tags_for_model(Video),
                "user_can_add": user_can_add,
                "collections": None,
                "current_collection": None,
            },
        )


def add(request: AuthenticatedHttpRequest) -> HttpResponse:
    if not video_permission_policy.user_has_permission(request.user, "add"):
        raise PermissionDenied
    video_form = cast(Any, get_video_form())
    if request.POST:
        video = Video(user=request.user)
        form = video_form(request.POST, request.FILES, instance=video, user=request.user)
        if form.is_valid():
            form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(video)

            messages.success(
                request,
                _("Video file '{0}' added.").format(video.title),
                buttons=[messages.button(reverse("castvideo:edit", args=(video.id,)), _("Edit"))],
            )
            return redirect("castvideo:index")
        else:
            messages.error(request, _("The video file could not be saved due to errors."))
    else:
        video = Video(user=request.user)
        form = video_form(instance=video, user=request.user)

    return render(
        request,
        "cast/video/add.html",
        {"form": form},
    )


def edit(request: HttpRequest, video_id: int) -> HttpResponse:
    video_form = cast(Any, get_video_form())
    video = get_object_or_404(
        video_permission_policy.instances_user_has_permission_for(request.user, "change"),
        id=video_id,
    )

    if request.POST:
        original_file = video.original
        form = video_form(request.POST, request.FILES, instance=video, user=request.user)
        if form.is_valid():
            if "original" in form.changed_data:
                # if providing a new video file, delete the old one.
                # NB Doing this via original_file.delete() clears the file field,
                # which definitely isn't what we want...
                if original_file.name:
                    original_file.storage.delete(original_file.name)
            video = form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(video)

            messages.success(
                request,
                _("Video file '{0}' updated").format(video.title),
                buttons=[messages.button(reverse("castvideo:edit", args=(video.id,)), _("Edit"))],
            )
            return redirect("castvideo:index")
        else:
            messages.error(request, _("The media could not be saved due to errors."))
    else:
        form = video_form(instance=video, user=request.user)

    filesize = None

    # Get file size when there is a file associated with the Media object
    if video.original:
        try:
            filesize = video.original.size
        except OSError:
            # File doesn't exist
            pass

    if not filesize:
        messages.error(
            request,
            _("The file could not be found. Please change the source or delete the video file"),
            buttons=[messages.button(reverse("castvideo:delete", args=(video.id,)), _("Delete"))],
        )

    return render(
        request,
        "cast/video/edit.html",
        {
            "video": video,
            "filesize": filesize,
            "form": form,
            "user_can_delete": video_permission_policy.user_has_permission_for_instance(request.user, "delete", video),
        },
    )


def delete(request: HttpRequest, video_id: int) -> HttpResponse:
    video = get_object_or_404(
        video_permission_policy.instances_user_has_permission_for(request.user, "delete"),
        id=video_id,
    )

    if request.POST:
        video.delete()
        messages.success(request, _("Video '{0}' deleted.").format(video.title))
        return redirect("castvideo:index")

    return render(request, "cast/video/confirm_delete.html", {"video": video})


def chooser(request: HttpRequest) -> HttpResponse:
    if not video_permission_policy.user_has_permission(request.user, "choose"):
        raise PermissionDenied
    ordering = "-created"
    base_videos = video_permission_policy.instances_user_has_permission_for(request.user, "choose").order_by(ordering)
    videos: models.QuerySet | BaseSearchResults = base_videos

    upload_form = cast(Any, get_video_form())(prefix="media-chooser-upload", user=request.user)

    if "q" in request.GET or "p" in request.GET:
        search_form = NonEmptySearchForm(request.GET)
        if search_form.is_valid():
            raw_query_string = search_form.cleaned_data["q"]
            videos = safe_modelsearch_results(base_videos, raw_query_string)
            q = normalize_modelsearch_query(raw_query_string) or None
            is_searching = bool(q)
        else:
            q = None
            is_searching = False

        paginator, video_items = paginate(request, videos, per_page=CHOOSER_PAGINATION)
        return render(
            request,
            "cast/video/chooser_results.html",
            {
                "videos": video_items,
                "query_string": q,
                "is_searching": is_searching,
                "pagination_template": pagination_template,
            },
        )
    else:
        search_form = NonEmptySearchForm()
        paginator, video_items = paginate(request, videos, per_page=CHOOSER_PAGINATION)

    return render_modal_workflow(
        request,
        "cast/video/chooser_chooser.html",
        None,
        {
            "videos": video_items,
            "searchform": search_form,
            "uploadform": upload_form,
            "is_searching": False,
            "pagination_template": pagination_template,
        },
        json_data={
            "step": "chooser",
            "error_label": "Server Error",
            "error_message": "Report this error to your webmaster with the following information:",
            "tag_autocomplete_url": reverse("wagtailadmin_tag_autocomplete"),
        },
    )


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


def chosen(request: HttpRequest, video_id: int) -> HttpResponse:
    video = get_object_or_404(
        video_permission_policy.instances_user_has_permission_for(request.user, "choose"),
        id=video_id,
    )

    return render_modal_workflow(
        request,
        None,
        None,
        None,
        json_data={"step": "video_chosen", "result": get_video_data(video)},
    )


def chooser_upload(request: AuthenticatedHttpRequest) -> HttpResponse:
    if not video_permission_policy.user_has_permission(
        request.user, "add"
    ) or not video_permission_policy.user_has_permission(request.user, "choose"):
        raise PermissionDenied
    VideoForm = cast(Any, get_video_form())

    if request.method == "POST":
        video = Video(user=request.user)
        form = VideoForm(request.POST, request.FILES, instance=video, user=request.user, prefix="media-chooser-upload")

        if form.is_valid():
            form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(video)

            return render_modal_workflow(
                request,
                None,
                None,
                None,
                json_data={"step": "video_chosen", "result": get_video_data(video)},
            )
        else:
            messages.error(request, _("The video could not be saved due to errors."))

    ordering = "-created"
    videos = video_permission_policy.instances_user_has_permission_for(request.user, "choose").order_by(ordering)

    search_form = NonEmptySearchForm()

    paginator, video_items = paginate(request, videos, per_page=10)

    context = {
        "videos": video_items,
        "searchform": search_form,
        # "collections": collections,
        "uploadform": VideoForm(user=request.user),
        "is_searching": False,
        "pagination_template": pagination_template,
    }
    return render_modal_workflow(
        request,
        "cast/video/chooser_chooser.html",
        None,
        context,
        json_data={"step": "chooser"},
    )
