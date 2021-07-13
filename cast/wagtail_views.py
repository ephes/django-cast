from django.shortcuts import render
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers

from wagtailmedia.utils import paginate
from wagtail.admin.auth import permission_denied
from wagtail.admin.models import popular_tags_for_model
from wagtailmedia.permissions import permission_policy
from wagtail.admin.auth import PermissionPolicyChecker
from wagtail.admin.forms.search import SearchForm

from .models import Video

permission_checker = PermissionPolicyChecker(permission_policy)


@permission_checker.require_any("add", "change", "delete")
@vary_on_headers("X-Requested-With")
def video_index(request):
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

    collections = permission_policy.collections_user_has_any_permission_for(
        request.user, ["add", "change"]
    )
    if len(collections) < 2:
        collections = None

    # Create response
    print("fooobarbz")
    print(request.headers.get("x-requested-with"))
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(
            request,
            "wagtailmedia/media/results.html",
            {
                "ordering": ordering,
                "media_files": media,
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
                "media_files": media,
                "query_string": query_string,
                "is_searching": bool(query_string),
                "search_form": form,
                "popular_tags": popular_tags_for_model(Video),
                "user_can_add": permission_policy.user_has_permission(request.user, "add"),
                "collections": collections,
                "current_collection": None,
            },
        )

from django.urls import reverse
from django.shortcuts import redirect

from wagtail.admin import messages
from wagtail.search.backends import get_search_backends

from .models import Video
from .wagtail_forms import get_video_form


@permission_checker.require("add")
def video_add(request):
    VideoForm = get_video_form()
    if request.POST:
        video = Video(user=request.user)
        form = VideoForm(request.POST, request.FILES, instance=video, user=request.user)
        if form.is_valid():
            form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(video)

            messages.success(
                request,
                _("Video file '{0}' added.").format(video.title),
                buttons=[
                    messages.button(
                        reverse("castmedia:edit", args=(video.id,)), _("Edit")
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


@permission_checker.require("change")
def video_edit(request, video_id):
    VideoForm = get_video_form()
    video = get_object_or_404(Video, id=video_id)

    if not permission_policy.user_has_permission_for_instance(request.user, "change", video):
        return permission_denied(request)

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
                        reverse("castmedia:edit", args=(video.id,)), _("Edit")
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
            "user_can_delete": permission_policy.user_has_permission_for_instance(request.user, "delete", video),
        },
    )


@permission_checker.require("delete")
def video_delete(request, video_id):
    video = get_object_or_404(Video, id=video_id)

    if not permission_policy.user_has_permission_for_instance(request.user, "delete", video):
        return permission_denied(request)

    if request.POST:
        video.delete()
        messages.success(request, _("Video '{0}' deleted.").format(video.title))
        return redirect("castmedia:video_index")

    return render(request, "cast/wagtail/video_confirm_delete.html", {"video": video})
