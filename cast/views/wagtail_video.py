from django.shortcuts import render
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers

from wagtail.admin.forms.search import SearchForm
from wagtail.admin.models import popular_tags_for_model
from wagtail.admin.modal_workflow import render_modal_workflow


DEFAULT_PAGE_KEY = "p"


def paginate(request, items, page_key=DEFAULT_PAGE_KEY, per_page=20):
    paginator = Paginator(items, per_page)
    page = paginator.get_page(request.GET.get(page_key))
    return paginator, page

@vary_on_headers("X-Requested-With")
def index(request):
    ordering = "-created"
    videos = Video.objects.all().order_by(ordering)

    # Search
    query_string = None
    if "q" in request.GET:
        form = SearchForm(request.GET, placeholder=_("Search video files"))
        if form.is_valid():
            query_string = form.cleaned_data["q"]
            videos = videos.search(query_string)
    else:
        form = SearchForm(placeholder=_("Search media"))

    # Pagination
    paginator, media = paginate(request, videos)

    # Create response
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(
            request,
            "cast/wagtail/video_chooser_results.html",
            {
                "ordering": ordering,
                "videos": videos,
                "query_string": query_string,
                "is_searching": bool(query_string),
            },
        )
    else:
        return render(
            request,
            "cast/wagtail/video_index.html",
            {
                "ordering": ordering,
                "videos": videos,
                "query_string": query_string,
                "is_searching": bool(query_string),
                "search_form": form,
                "popular_tags": popular_tags_for_model(Video),
                "user_can_add": True,
                "collections": None,
                "current_collection": None,
            },
        )

from django.urls import reverse
from django.shortcuts import redirect

from wagtail.admin import messages
from wagtail.search.backends import get_search_backends

from ..models import Video
from ..wagtail_forms import get_video_form


def add(request):
    VideoForm = get_video_form()
    if request.POST:
        video = Video(user=request.user)
        form = VideoForm(request.POST, request.FILES, instance=video, user=request.user)
        if form.is_valid():
            print("form is valid?!")
            form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(video)

            messages.success(
                request,
                _("Video file '{0}' added.").format(video.title),
                buttons=[
                    messages.button(
                        reverse("castmedia:video_edit", args=(video.id,)), _("Edit")
                    )
                ],
            )
            return redirect("castmedia:video_index")
        else:
            messages.error(
                request, _("The video file could not be saved due to errors.")
            )
    else:
        video = Video(user=request.user)
        form = VideoForm(user=request.user, instance=video)

    return render(
        request,
        "cast/wagtail/video_add.html",
        {"form": form},
    )


def edit(request, video_id):
    VideoForm = get_video_form()
    video = get_object_or_404(Video, id=video_id)

    if request.POST:
        original_file = video.original
        form = VideoForm(request.POST, request.FILES, instance=video, user=request.user)
        if form.is_valid():
            if "file" in form.changed_data:
                # if providing a new media file, delete the old one.
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
                buttons=[
                    messages.button(
                        reverse("castmedia:video_edit", args=(video.id,)), _("Edit")
                    )
                ],
            )
            return redirect("castmedia:video_index")
        else:
            messages.error(request, _("The media could not be saved due to errors."))
    else:
        form = VideoForm(instance=video, user=request.user)

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
            _(
                "The file could not be found. Please change the source or delete the video file"
            ),
            buttons=[
                messages.button(
                    reverse("castmedia:delete", args=(video.id,)), _("Delete")
                )
            ],
        )

    return render(
        request,
        "cast/wagtail/video_edit.html",
        {
            "video": video,
            "filesize": filesize,
            "form": form,
            "user_can_delete": True,
        },
    )


def delete(request, video_id):
    video = get_object_or_404(Video, id=video_id)

    if request.POST:
        video.delete()
        messages.success(request, _("Video '{0}' deleted.").format(video.title))
        return redirect("castmedia:video_index")

    return render(request, "cast/wagtail/video_confirm_delete.html", {"video": video})


def chooser(request):
    ordering = "-created"
    videos = Video.objects.all().order_by(ordering)

    upload_form = get_video_form()

    paginator, videos = paginate(request, videos, per_page=10)

    return render_modal_workflow(
        request,
        "cast/wagtail/video_chooser_chooser.html",
        None,
        {
            "videos": videos,
            "uploadform": upload_form,
            "is_searching": False,
            "pagination_template": "wagtailadmin/shared/ajax_pagination_nav.html",
        },
        json_data={
            "step": "chooser",
            "error_label": "Server Error",
            "error_message": "Report this error to your webmaster with the following information:",
            "tag_autocomplete_url": reverse("wagtailadmin_tag_autocomplete"),
        },
    )


def get_data(video):
    """
    helper function: given a video, return the data to pass back to the
    chooser panel as the result of ModalWorkflow
    """

    return {
        "id": video.id,
        "title": video.title,
        "edit_url": reverse("castmedia:video_edit", args=(video.id,)),
    }


def chosen(request, video_id):
    video = get_object_or_404(Video, id=video_id)

    return render_modal_workflow(
        request,
        None,
        None,
        None,
        json_data={"step": "video_chosen", "result": get_video_data(video)},
    )


def chooser_upload(request):
    VideoForm = get_video_form()

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

    ordering = "-created"
    videos = Video.objects.all().order_by(ordering)

    search_form = SearchForm()

    paginator, videos = paginate(request, videos, per_page=10)

    context = {
        "videos": videos,
        "searchform": search_form,
        # "collections": collections,
        "uploadform": form,
        "is_searching": False,
        "pagination_template": "wagtailadmin/shared/ajax_pagination_nav.html",
    }
    return render_modal_workflow(
        request,
        "cast/wagtail/video_chooser_chooser.html",
        None,
        context,
        json_data={"step": "chooser"},
    )
