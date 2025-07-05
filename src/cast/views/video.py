from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers
from wagtail.admin import messages
from wagtail.admin.modal_workflow import render_modal_workflow
from wagtail.admin.models import popular_tags_for_model
from wagtail.search.backends import get_search_backends

from ..appsettings import CHOOSER_PAGINATION, MENU_ITEM_PAGINATION
from ..forms import NonEmptySearchForm, get_video_form
from ..models import Video
from . import AuthenticatedHttpRequest
from .wagtail_pagination import paginate, pagination_template


@vary_on_headers("X-Requested-With")
def index(request: HttpRequest) -> HttpResponse:
    ordering = "-created"
    videos = Video.objects.all().order_by(ordering)

    # Search
    query_string = None
    if "q" in request.GET:
        form = NonEmptySearchForm(request.GET, placeholder=_("Search video files"))
        if form.is_valid():
            query_string = form.cleaned_data["q"]
            videos = videos.search(query_string)
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
                "user_can_add": True,
                "collections": None,
                "current_collection": None,
            },
        )


def add(request: AuthenticatedHttpRequest) -> HttpResponse:
    video_form = get_video_form()
    if request.POST:
        video = Video(user=request.user)
        form = video_form(request.POST, request.FILES, instance=video)
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
        form = video_form(instance=video)

    return render(
        request,
        "cast/video/add.html",
        {"form": form},
    )


def edit(request: HttpRequest, video_id: int) -> HttpResponse:
    video_form = get_video_form()
    video = get_object_or_404(Video, id=video_id)

    if request.POST:
        original_file = video.original
        form = video_form(request.POST, request.FILES, instance=video)
        if form.is_valid():
            if "original" in form.changed_data:
                # if providing a new video file, delete the old one.
                # NB Doing this via original_file.delete() clears the file field,
                # which definitely isn't what we want...
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
        form = video_form(instance=video)

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
            "user_can_delete": True,
        },
    )


def delete(request: HttpRequest, video_id: int) -> HttpResponse:
    video = get_object_or_404(Video, id=video_id)

    if request.POST:
        video.delete()
        messages.success(request, _("Video '{0}' deleted.").format(video.title))
        return redirect("castvideo:index")

    return render(request, "cast/video/confirm_delete.html", {"video": video})


def chooser(request: HttpRequest) -> HttpResponse:
    ordering = "-created"
    videos = Video.objects.all().order_by(ordering)

    upload_form = get_video_form()(prefix="media-chooser-upload")

    if "q" in request.GET or "p" in request.GET:
        search_form = NonEmptySearchForm(request.GET)
        if search_form.is_valid():
            q = search_form.cleaned_data["q"]

            videos = videos.search(q)
            is_searching = True
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
    video = get_object_or_404(Video, id=video_id)

    return render_modal_workflow(
        request,
        None,
        None,
        None,
        json_data={"step": "video_chosen", "result": get_video_data(video)},
    )


def chooser_upload(request: AuthenticatedHttpRequest) -> HttpResponse:
    VideoForm = get_video_form()

    if request.method == "POST":
        video = Video(user=request.user)
        form = VideoForm(request.POST, request.FILES, instance=video, prefix="media-chooser-upload")

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
    videos = Video.objects.all().order_by(ordering)

    search_form = NonEmptySearchForm()

    paginator, video_items = paginate(request, videos, per_page=10)

    context = {
        "videos": video_items,
        "searchform": search_form,
        # "collections": collections,
        "uploadform": VideoForm(),
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
