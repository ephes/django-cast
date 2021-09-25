from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers

from wagtail.admin import messages
from wagtail.admin.forms.search import SearchForm
from wagtail.admin.modal_workflow import render_modal_workflow
from wagtail.admin.models import popular_tags_for_model
from wagtail.search.backends import get_search_backends

from ..appsettings import CHOOSER_PAGINATION, MENU_ITEM_PAGINATION
from ..forms import AudioForm
from ..models import Audio


DEFAULT_PAGE_KEY = "p"

pagination_template = "wagtailadmin/shared/ajax_pagination_nav.html"


def paginate(request, items, page_key=DEFAULT_PAGE_KEY, per_page=MENU_ITEM_PAGINATION):
    paginator = Paginator(items, per_page)
    page = paginator.get_page(request.GET.get(page_key))
    return paginator, page


@vary_on_headers("X-Requested-With")
def index(request):
    ordering = "-created"
    audios = Audio.objects.all().order_by(ordering)

    # Search
    query_string = None
    if "q" in request.GET:
        form = SearchForm(request.GET, placeholder=_("Search audio files"))
        if form.is_valid():
            query_string = form.cleaned_data["q"]
            audios = audios.search(query_string)
    else:
        form = SearchForm(placeholder=_("Search media"))

    # Pagination
    paginator, audios = paginate(request, audios, per_page=MENU_ITEM_PAGINATION)

    # Create response
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(
            request,
            "cast/audio/results.html",
            {
                "ordering": ordering,
                "audios": audios,
                "query_string": query_string,
                "is_searching": bool(query_string),
            },
        )
    else:
        return render(
            request,
            "cast/audio/index.html",
            {
                "ordering": ordering,
                "audios": audios,
                "query_string": query_string,
                "is_searching": bool(query_string),
                "search_form": form,
                "popular_tags": popular_tags_for_model(Audio),
                "user_can_add": True,
                "collections": None,
                "current_collection": None,
            },
        )


def add(request):
    if request.POST:
        audio = Audio(user=request.user)
        form = AudioForm(request.POST, request.FILES, instance=audio, user=request.user)
        if form.is_valid():
            form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(audio)

            messages.success(
                request,
                _("Audio file '{0}' added.").format(audio.title),
                buttons=[messages.button(reverse("castaudio:edit", args=(audio.id,)), _("Edit"))],
            )
            return redirect("castaudio:index")
        else:
            messages.error(request, _("The audio file could not be saved due to errors."))
    else:
        audio = Audio(user=request.user)
        form = AudioForm(user=request.user, instance=audio)

    return render(
        request,
        "cast/audio/add.html",
        {"form": form},
    )


def edit(request, audio_id):
    audio = get_object_or_404(Audio, id=audio_id)

    if request.method == "POST":
        form = AudioForm(request.POST, request.FILES, instance=audio, user=request.user)
        if form.is_valid():
            changed_audio_files = set(form.changed_data).intersection(audio.audio_formats)
            if len(changed_audio_files) > 0:
                # FIXME butt ugly
                old_audio = get_object_or_404(Audio, id=audio_id)
            for file_format in changed_audio_files:
                # if providing a new audio file, delete the old one.
                # NB Doing this via original_file.delete() clears the file field,
                # which definitely isn't what we want...
                original_file = getattr(old_audio, file_format)
                if original_file.name != "":
                    original_file.storage.delete(original_file.name)
            audio = form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(audio)

            messages.success(
                request,
                _("Audio file '{0}' updated").format(audio.title),
                buttons=[messages.button(reverse("castaudio:edit", args=(audio.id,)), _("Edit"))],
            )
            return redirect("castaudio:index")
        else:
            messages.error(request, _("The media could not be saved due to errors."))
    else:
        form = AudioForm(instance=audio, user=request.user, initial={"chaptermarks": audio.chapters_as_text})

    filesize = None

    # Get file size when there is a file associated with the Media object
    if audio.m4a:
        try:
            filesize = audio.m4a.size
        except OSError:
            # File doesn't exist
            pass

    if not filesize:
        messages.error(
            request,
            _("The file could not be found. Please change the source or delete the audio file"),
            buttons=[messages.button(reverse("castaudio:delete", args=(audio.id,)), _("Delete"))],
        )

    return render(
        request,
        "cast/audio/edit.html",
        {
            "audio": audio,
            "filesize": filesize,
            "form": form,
            "user_can_delete": True,
        },
    )


def delete(request, audio_id):
    audio = get_object_or_404(Audio, id=audio_id)

    if request.POST:
        audio.delete()
        messages.success(request, _("Audio '{0}' deleted.").format(audio.title))
        return redirect("castaudio:index")

    return render(request, "cast/audio/confirm_delete.html", {"audio": audio})


def chooser(request):
    ordering = "-created"
    audios = Audio.objects.all().order_by(ordering)

    upload_form = AudioForm(prefix="media-chooser-upload")

    if "q" in request.GET or "p" in request.GET:
        search_form = SearchForm(request.GET)
        if search_form.is_valid():
            q = search_form.cleaned_data["q"]

            audios = audios.search(q)
            is_searching = True
        else:
            q = None
            is_searching = False

        paginator, audios = paginate(request, audios, per_page=CHOOSER_PAGINATION)
        return render(
            request,
            "cast/audio/chooser_results.html",
            {
                "audios": audios,
                "query_string": q,
                "is_searching": is_searching,
                "pagination_template": pagination_template,
            },
        )
    else:
        search_form = SearchForm()
        paginator, audios = paginate(request, audios, per_page=CHOOSER_PAGINATION)

    return render_modal_workflow(
        request,
        "cast/audio/chooser_chooser.html",
        None,
        {
            "audios": audios,
            "uploadform": upload_form,
            "searchform": search_form,
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


def get_audio_data(audio):
    """
    helper function: given a audio, return the json to pass back to the
    chooser panel - move to model FIXME
    """
    return {
        "id": audio.id,
        "title": audio.title,
        "edit_link": reverse("castaudio:edit", args=(audio.id,)),
    }


def chosen(request, audio_id):
    audio = get_object_or_404(Audio, id=audio_id)

    return render_modal_workflow(
        request,
        None,
        None,
        None,
        json_data={"step": "audio_chosen", "result": get_audio_data(audio)},
    )


def chooser_upload(request):
    if request.method == "POST":
        audio = Audio(user=request.user)
        form = AudioForm(request.POST, request.FILES, instance=audio, user=request.user, prefix="media-chooser-upload")

        if form.is_valid():
            form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(audio)

            return render_modal_workflow(
                request,
                None,
                None,
                None,
                json_data={"step": "audio_chosen", "result": get_audio_data(audio)},
            )
        else:
            messages.error(request, _("The audio could not be saved due to errors."))

    ordering = "-created"
    audios = Audio.objects.all().order_by(ordering)

    search_form = SearchForm()

    paginator, audios = paginate(request, audios, per_page=CHOOSER_PAGINATION)

    context = {
        "audios": audios,
        "searchform": search_form,
        # "collections": collections,
        "uploadform": AudioForm(),
        "is_searching": False,
        "pagination_template": "wagtailadmin/shared/ajax_pagination_nav.html",
    }
    return render_modal_workflow(
        request,
        "cast/audio/chooser_chooser.html",
        None,
        context,
        json_data={"step": "chooser"},
    )
