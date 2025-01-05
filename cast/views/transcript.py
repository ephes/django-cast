import json
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers
from wagtail.admin import messages
from wagtail.admin.modal_workflow import render_modal_workflow
from wagtail.search.backends import get_search_backends

from ..appsettings import CHOOSER_PAGINATION, MENU_ITEM_PAGINATION
from ..forms import NonEmptySearchForm, TranscriptForm
from ..models import Transcript
from . import AuthenticatedHttpRequest
from .wagtail_pagination import paginate, pagination_template


@vary_on_headers("X-Requested-With")
def index(request: HttpRequest) -> HttpResponse:
    transcripts = Transcript.objects.all()

    # Search
    query_string = None
    if "q" in request.GET:
        form = NonEmptySearchForm(request.GET, placeholder=_("Search transcript files"))
        if form.is_valid():
            query_string = form.cleaned_data["q"]
            transcripts = transcripts.filter(audio__title__icontains=query_string)
    else:
        form = NonEmptySearchForm(placeholder=_("Search transcripts"))

    # Pagination
    paginator, transcript_items = paginate(request, transcripts, per_page=MENU_ITEM_PAGINATION)

    # Create response
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return render(
            request,
            "cast/transcript/results.html",
            {
                "transcripts": transcript_items,
                "query_string": query_string,
                "is_searching": bool(query_string),
            },
        )
    else:
        return render(
            request,
            "cast/transcript/index.html",
            {
                "transcripts": transcript_items,
                "query_string": query_string,
                "is_searching": bool(query_string),
                "search_form": form,
                "user_can_add": True,
                "collections": None,
                "current_collection": None,
            },
        )


def add(request: AuthenticatedHttpRequest) -> HttpResponse:
    if request.POST:
        transcript = Transcript()
        form = TranscriptForm(request.POST, request.FILES, instance=transcript)
        if form.is_valid():
            form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(transcript)

            messages.success(
                request,
                _("Transcript file '{0}' added.").format(transcript.pk),
                buttons=[messages.button(reverse("cast-transcript:edit", args=(transcript.id,)), _("Edit"))],
            )
            return redirect("cast-transcript:index")
        else:
            messages.error(request, _("The transcript file could not be saved due to errors."))
    else:
        transcript = Transcript()
        form = TranscriptForm(instance=transcript)

    return render(
        request,
        "cast/transcript/add.html",
        {"form": form},
    )


def edit(request: HttpRequest, transcript_id: int) -> HttpResponse:
    transcript = get_object_or_404(Transcript, id=transcript_id)

    if request.method == "POST":
        form = TranscriptForm(request.POST, request.FILES, instance=transcript)
        if form.is_valid():
            transcript = form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(transcript)

            messages.success(
                request,
                _("Transcript file '{0}' updated").format(transcript.pk),
                buttons=[messages.button(reverse("cast-transcript:edit", args=(transcript.id,)), _("Edit"))],
            )
            return redirect("cast-transcript:index")
        else:
            messages.error(request, _("The transcript could not be saved due to errors."))
    else:
        form = TranscriptForm(instance=transcript)

    return render(
        request,
        "cast/transcript/edit.html",
        {
            "transcript": transcript,
            "form": form,
            "user_can_delete": True,
        },
    )


def delete(request: HttpRequest, transcript_id: int) -> HttpResponse:
    transcript = get_object_or_404(Transcript, id=transcript_id)

    if request.POST:
        transcript.delete()
        messages.success(request, _("Transcript '{0}' deleted.").format(transcript.pk))
        return redirect("cast-transcript:index")

    return render(request, "cast/transcript/confirm_delete.html", {"transcript": transcript})


def chooser(request: HttpRequest) -> HttpResponse:
    transcripts = Transcript.objects.all()

    upload_form = TranscriptForm(prefix="media-chooser-upload")

    if "q" in request.GET or "p" in request.GET:
        search_form = NonEmptySearchForm(request.GET)
        if search_form.is_valid():
            q = search_form.cleaned_data["q"]

            transcripts = transcripts.filter(audio__title__icontains=q)
            is_searching = True
        else:
            q = None
            is_searching = False

        paginator, transcript_items = paginate(request, transcripts, per_page=CHOOSER_PAGINATION)
        return render(
            request,
            "cast/transcript/chooser_results.html",
            {
                "transcripts": transcript_items,
                "query_string": q,
                "is_searching": is_searching,
                "pagination_template": pagination_template,
            },
        )
    else:
        search_form = NonEmptySearchForm()
        paginator, transcript_items = paginate(request, transcripts, per_page=CHOOSER_PAGINATION)

    return render_modal_workflow(
        request,
        "cast/transcript/chooser_chooser.html",
        None,
        {
            "transcripts": transcript_items,
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


def get_transcript_data(transcript: Transcript) -> dict[str, Any]:
    """
    helper function: given a transcript, return the json to pass back to the
    chooser panel - move to model FIXME
    """
    return {
        "id": transcript.id,
        "edit_link": reverse("cast-transcript:edit", args=(transcript.id,)),
    }


def chosen(request, transcript_id: int) -> HttpResponse:
    transcript = get_object_or_404(Transcript, id=transcript_id)

    return render_modal_workflow(
        request,
        None,
        None,
        None,
        json_data={"step": "transcript_chosen", "result": get_transcript_data(transcript)},
    )


def chooser_upload(request: AuthenticatedHttpRequest) -> HttpResponse:
    if request.method == "POST":
        transcript = Transcript()
        form = TranscriptForm(request.POST, request.FILES, instance=transcript, prefix="media-chooser-upload")

        if form.is_valid():
            form.save()

            # Reindex the media entry to make sure all tags are indexed
            for backend in get_search_backends():
                backend.add(transcript)

            return render_modal_workflow(
                request,
                None,
                None,
                None,
                json_data={"step": "transcript_chosen", "result": get_transcript_data(transcript)},
            )
        else:
            messages.error(request, _("The transcript could not be saved due to errors."))

    transcripts = Transcript.objects.all()

    search_form = NonEmptySearchForm()

    paginator, transcript_items = paginate(request, transcripts, per_page=CHOOSER_PAGINATION)

    context = {
        "transcripts": transcript_items,
        "searchform": search_form,
        # "collections": collections,
        "uploadform": TranscriptForm(),
        "is_searching": False,
        "pagination_template": "wagtailadmin/shared/ajax_pagination_nav.html",
    }
    return render_modal_workflow(
        request,
        "cast/transcript/chooser_chooser.html",
        None,
        context,
        json_data={"step": "chooser"},
    )


def podlove_transcript_json(_request: HttpRequest, pk):
    """Return the podlove transcript content as JSON because of CORS restrictions."""
    transcript = get_object_or_404(Transcript, pk=pk)
    if transcript.podlove:
        # Open the file and load its contents as JSON
        with transcript.podlove.open("r") as file:
            try:
                data = json.load(file)  # assumes the file content is JSON
            except json.JSONDecodeError:
                return HttpResponse("Invalid JSON format in podlove file", status=400)
        return JsonResponse(data)
    return HttpResponse("Podlove file not available", status=404)
