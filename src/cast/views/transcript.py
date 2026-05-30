import json
from typing import Any, TypedDict, cast

from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.vary import vary_on_headers
from wagtail.admin import messages
from wagtail.admin.modal_workflow import render_modal_workflow
from wagtail.search.backends import get_search_backends

from ..appsettings import CHOOSER_PAGINATION, MENU_ITEM_PAGINATION
from ..forms import (
    KNOWN_SPEAKER_APPLY_ACTION,
    KNOWN_SPEAKER_REVIEW_ACTION,
    KnownSpeakerSegmentReviewForm,
    NonEmptySearchForm,
    SpeakerContributorMappingForm,
    SPEAKER_MAPPING_ACTION,
    TranscriptForm,
    VoiceReferenceCandidateCreateForm,
    VOICE_REFERENCE_CREATE_ACTION,
)
from ..models import (
    Blog,
    Contributor,
    Episode,
    EpisodeContributor,
    Post,
    Transcript,
    TranscriptSpeakerSample,
    TranscriptVoiceReferenceCandidate,
    get_template_base_dir,
)
from ..models.contributors import ContributorVoiceReference
from ..models.transcript import _dote_timestamp_to_ms, convert_dote_to_podcastindex_transcript
from ..site_lookup import get_site_specific_page_or_404
from ..transcript_sanitization import (
    public_episode_from_request,
    sanitize_dote_data,
    sanitize_podlove_data,
    sanitize_webvtt_content,
    strict_public_speaker_labels_for_transcript,
)
from . import AuthenticatedHttpRequest, HtmxHttpRequest
from .wagtail_pagination import paginate, pagination_template


TRANSCRIPT_FALLBACK_THEME = "plain"


class SpeakerMappingContext(TypedDict):
    contributor_assignments: list[EpisodeContributor]
    multiple_episodes: bool
    speaker_labels: list[str]
    source_episode: Episode | None


class SpeakerMappingRow(TypedDict):
    field: BoundField
    samples: list[TranscriptSpeakerSample]


class VoiceReferenceCandidateRow(TypedDict):
    candidate: TranscriptVoiceReferenceCandidate
    contributor: Contributor | None
    duplicate_reference: ContributorVoiceReference | None
    form_id: str


class VoiceReferenceCandidateGroup(TypedDict):
    contributor: Contributor | None
    speaker_label: str
    rows: list[VoiceReferenceCandidateRow]


class KnownSpeakerReviewRow(TypedDict):
    confidence: Any
    field: BoundField
    margin: Any
    speaker: str
    text: str
    timestamp_label: str
    uncertain: bool


class AudioSource(TypedDict):
    mimeType: str
    size: str
    title: str
    url: str


def _resolve_transcript_template(base_template_dir: str) -> str:
    """Return the transcript template path, falling back to plain if needed."""
    candidate = f"cast/{base_template_dir}/transcript.html"
    try:
        get_template(candidate)
        return candidate
    except TemplateDoesNotExist:
        return f"cast/{TRANSCRIPT_FALLBACK_THEME}/transcript.html"


def _render_transcript_html(
    request: HtmxHttpRequest,
    transcript: Transcript,
    base_template_dir: str,
    *,
    episode: Episode | None = None,
) -> HttpResponse:
    if not transcript.podlove:
        return HttpResponse("Transcript JSON not available", status=404)
    try:
        data = transcript.podlove_data
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON format in podlove file", status=400)
    data = sanitize_podlove_data(data, strict_public_speaker_labels_for_transcript(transcript, episode=episode))
    if episode is not None:
        context = episode.get_context(request)
        context["episode"] = episode
        context["episode_url"] = context.get("page_url") or episode.get_url(request=request)
        context["transcript"] = data
    else:
        context = {"transcript": data, "episode": None}
    template_name = _resolve_transcript_template(base_template_dir)
    return render(request, template_name, context)


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
        form = TranscriptForm(request.POST, request.FILES, instance=transcript, user=request.user)
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
        form = TranscriptForm(instance=transcript, user=request.user)

    return render(
        request,
        "cast/transcript/add.html",
        {"form": form},
    )


def _episode_from_latest_revision(episode: Episode) -> Episode:
    return cast(Episode, episode.get_latest_revision_as_object())


def get_speaker_mapping_context(transcript: Transcript) -> SpeakerMappingContext:
    episodes = [
        _episode_from_latest_revision(episode)
        for episode in transcript.audio.episodes.select_related("latest_revision")
        .prefetch_related("contributor_assignments__contributor")
        .all()
    ]
    contributor_assignments: list[EpisodeContributor] = []
    for episode in episodes:
        contributor_assignments.extend(episode.visible_contributor_assignments)
    speaker_labels = transcript.get_speaker_labels()
    return {
        "contributor_assignments": contributor_assignments,
        "multiple_episodes": len(episodes) > 1,
        "speaker_labels": speaker_labels,
        "source_episode": episodes[0] if len(episodes) == 1 else None,
    }


def get_speaker_mapping_rows(
    speaker_mapping_form: SpeakerContributorMappingForm,
    speaker_samples: dict[str, list[TranscriptSpeakerSample]],
) -> list[SpeakerMappingRow]:
    return [
        {
            "field": speaker_mapping_form[field_name],
            "samples": speaker_samples.get(speaker_label, []),
        }
        for field_name, speaker_label in speaker_mapping_form.speaker_field_names.items()
    ]


def get_known_speaker_text_by_start_ms(transcript: Transcript) -> dict[int, str]:
    texts: dict[int, str] = {}
    podlove_segments = transcript.podlove_data.get("transcripts", [])
    if isinstance(podlove_segments, list):
        for segment in podlove_segments:
            if not isinstance(segment, dict):
                continue
            start_ms = segment.get("start_ms")
            text = Transcript._clean_sample_text(segment.get("text"))
            if isinstance(start_ms, int) and text:
                texts.setdefault(start_ms, text)
    dote_lines = transcript.dote_data.get("lines", [])
    if isinstance(dote_lines, list):
        for line in dote_lines:
            if not isinstance(line, dict):
                continue
            start_ms = _dote_timestamp_to_ms(line.get("startTime"))
            text = Transcript._clean_sample_text(line.get("text"))
            if start_ms is not None and text:
                texts.setdefault(start_ms, text)
    return texts


def get_known_speaker_review_rows(
    transcript: Transcript,
    known_speaker_review_form: KnownSpeakerSegmentReviewForm,
) -> list[KnownSpeakerReviewRow]:
    text_by_start_ms = get_known_speaker_text_by_start_ms(transcript)
    rows: list[KnownSpeakerReviewRow] = []
    for field_name, position in known_speaker_review_form.segment_field_names.items():
        segment = known_speaker_review_form.segments[position]
        start_seconds = Transcript._parse_timestamp_seconds(segment.get("start"))
        start_ms = int(round(start_seconds * 1000)) if start_seconds is not None else None
        text = Transcript._clean_sample_text(segment.get("text"))
        if not text and start_ms is not None:
            text = text_by_start_ms.get(start_ms, "")
        rows.append(
            {
                "confidence": segment.get("confidence"),
                "field": known_speaker_review_form[field_name],
                "margin": segment.get("margin"),
                "speaker": Transcript._clean_speaker_label(segment.get("speaker")),
                "text": Transcript._truncate_sample_text(text, max_chars=140) if text else "",
                "timestamp_label": Transcript._format_sample_timestamp(start_seconds),
                "uncertain": bool(segment.get("speaker_uncertain") or segment.get("low_margin")),
            }
        )
    return rows


def resolve_voice_reference_contributor(
    speaker_label: str,
    contributor_assignments: list[EpisodeContributor],
) -> Contributor | None:
    contributors: dict[int, Contributor] = {}
    for assignment in contributor_assignments:
        if assignment.display_name != speaker_label or assignment.contributor_id is None:
            continue
        contributors[assignment.contributor_id] = assignment.contributor
    if len(contributors) == 1:
        return next(iter(contributors.values()))
    return None


def get_duplicate_voice_reference(
    *,
    transcript: Transcript,
    contributor: Contributor,
    candidate: TranscriptVoiceReferenceCandidate,
) -> ContributorVoiceReference | None:
    return (
        ContributorVoiceReference.objects.filter(
            contributor=contributor,
            source_audio=transcript.audio,
            start_seconds=candidate.start_seconds,
            end_seconds=candidate.end_seconds,
        )
        .order_by("pk")
        .first()
    )


def get_voice_reference_candidate_groups(
    transcript: Transcript,
    speaker_mapping_context: SpeakerMappingContext,
) -> list[VoiceReferenceCandidateGroup]:
    groups: dict[str, VoiceReferenceCandidateGroup] = {}
    candidates = transcript.get_voice_reference_candidates()
    for index, candidate in enumerate(candidates):
        contributor = resolve_voice_reference_contributor(
            candidate.speaker_label,
            speaker_mapping_context["contributor_assignments"],
        )
        group_key = (
            f"contributor:{contributor.pk}" if contributor is not None else f"speaker:{candidate.speaker_label}"
        )
        group = groups.setdefault(
            group_key,
            {
                "contributor": contributor,
                "speaker_label": candidate.speaker_label,
                "rows": [],
            },
        )
        duplicate_reference = (
            get_duplicate_voice_reference(transcript=transcript, contributor=contributor, candidate=candidate)
            if contributor is not None
            else None
        )
        group["rows"].append(
            {
                "candidate": candidate,
                "contributor": contributor,
                "duplicate_reference": duplicate_reference,
                "form_id": f"cast-voice-reference-{transcript.pk}-{index}",
            }
        )
    return list(groups.values())


def get_voice_reference_candidate(
    transcript: Transcript,
    *,
    speaker_label: str,
    candidate_rank: int,
) -> TranscriptVoiceReferenceCandidate | None:
    for candidate in transcript.get_voice_reference_candidates():
        if candidate.speaker_label == speaker_label and candidate.rank == candidate_rank:
            return candidate
    return None


def create_voice_reference_from_candidate(
    transcript: Transcript,
    speaker_mapping_context: SpeakerMappingContext,
    candidate: TranscriptVoiceReferenceCandidate,
    *,
    status: str,
    consent_confirmed: bool,
) -> tuple[ContributorVoiceReference, bool]:
    contributor = resolve_voice_reference_contributor(
        candidate.speaker_label,
        speaker_mapping_context["contributor_assignments"],
    )
    if contributor is None:
        raise ValidationError(
            _("Map this speaker label to one episode contributor before creating a voice reference.")
        )
    duplicate_reference = get_duplicate_voice_reference(
        transcript=transcript,
        contributor=contributor,
        candidate=candidate,
    )
    if duplicate_reference is not None:
        return duplicate_reference, False
    reference = ContributorVoiceReference(
        contributor=contributor,
        source_audio=transcript.audio,
        source_episode=speaker_mapping_context["source_episode"],
        start_seconds=candidate.start_seconds,
        end_seconds=candidate.end_seconds,
        status=status,
        consent_confirmed=consent_confirmed,
        notes=_("Created from transcript %(transcript_id)s, speaker label '%(speaker_label)s'.")
        % {"transcript_id": transcript.pk, "speaker_label": candidate.speaker_label},
    )
    reference.full_clean()
    reference.save()
    return reference, True


def validation_error_message(error: ValidationError) -> str:
    return " ".join(error.messages)


def get_transcript_audio_sources(transcript: Transcript) -> list[AudioSource]:
    sources: list[AudioSource] = []
    audio = transcript.audio
    for audio_format, field in audio.uploaded_audio_files:
        try:
            if not hasattr(field, "url"):
                continue
            if not field.storage.exists(field.name):
                continue
            file_size = audio.get_file_size(audio_format)
            url = field.url
        except (FileNotFoundError, OSError, ValueError):
            continue
        sources.append(
            {
                "mimeType": audio.mime_lookup[audio_format],
                "size": str(file_size),
                "title": str(audio.title_lookup[audio_format]),
                "url": url,
            }
        )
    return sources


def edit(request: HttpRequest, transcript_id: int) -> HttpResponse:
    transcript = get_object_or_404(Transcript, id=transcript_id)
    speaker_mapping_context = get_speaker_mapping_context(transcript)
    known_speaker_review_form: KnownSpeakerSegmentReviewForm | None = None

    if request.method == "POST" and request.POST.get("action") == KNOWN_SPEAKER_APPLY_ACTION:
        applied = transcript.apply_known_speaker_suggestions()
        if applied:
            messages.success(
                request,
                _("Applied known-speaker names to {0} public transcript entries.").format(applied),
            )
        else:
            messages.warning(request, _("No confident known-speaker suggestions were available to apply."))
        return redirect("cast-transcript:edit", transcript_id=transcript.id)
    elif request.method == "POST" and request.POST.get("action") == KNOWN_SPEAKER_REVIEW_ACTION:
        form = TranscriptForm(instance=transcript, user=request.user)
        speaker_mapping_form = SpeakerContributorMappingForm(**speaker_mapping_context)
        known_speaker_review_form = KnownSpeakerSegmentReviewForm(
            request.POST,
            segments=transcript.get_speaker_suggestions(),
            contributor_assignments=speaker_mapping_context["contributor_assignments"],
            multiple_episodes=speaker_mapping_context["multiple_episodes"],
        )
        if known_speaker_review_form.is_valid():
            changed = transcript.save_known_speaker_editor_decisions(known_speaker_review_form.segment_decisions)
            applied = transcript.apply_known_speaker_suggestions(smooth=False)
            if changed or applied:
                messages.success(
                    request,
                    _("Saved known-speaker segment decisions and applied {0} public transcript entries.").format(
                        applied
                    ),
                )
            else:
                messages.warning(request, _("No known-speaker segment decisions were changed."))
            return redirect("cast-transcript:edit", transcript_id=transcript.id)
        messages.error(request, _("The known-speaker segment decisions could not be saved due to errors."))
    elif request.method == "POST" and request.POST.get("action") == VOICE_REFERENCE_CREATE_ACTION:
        form = TranscriptForm(instance=transcript, user=request.user)
        speaker_mapping_form = SpeakerContributorMappingForm(**speaker_mapping_context)
        voice_reference_form = VoiceReferenceCandidateCreateForm(request.POST)
        if voice_reference_form.is_valid():
            candidate = get_voice_reference_candidate(
                transcript,
                speaker_label=voice_reference_form.cleaned_data["speaker_label"],
                candidate_rank=voice_reference_form.cleaned_data["candidate_rank"],
            )
            if candidate is None:
                messages.error(request, _("The selected voice-reference candidate is no longer available."))
            else:
                try:
                    reference, created = create_voice_reference_from_candidate(
                        transcript,
                        speaker_mapping_context,
                        candidate,
                        status=voice_reference_form.cleaned_data["voice_reference_status"],
                        consent_confirmed=voice_reference_form.cleaned_data["consent_confirmed"],
                    )
                except ValidationError as error:
                    messages.error(request, validation_error_message(error))
                else:
                    if created:
                        if reference.status == ContributorVoiceReference.Status.APPROVED:
                            messages.success(
                                request,
                                _("Created approved voice reference for {0}.").format(reference.contributor),
                            )
                        else:
                            messages.success(
                                request,
                                _("Saved pending voice reference for {0}.").format(reference.contributor),
                            )
                    else:
                        messages.warning(
                            request,
                            _("A voice reference for {0} already exists for this source range.").format(
                                reference.contributor
                            ),
                        )
                    return redirect("cast-transcript:edit", transcript_id=transcript.id)
        else:
            messages.error(request, _("The voice reference could not be created due to errors."))
    elif request.method == "POST" and request.POST.get("action") == SPEAKER_MAPPING_ACTION:
        form = TranscriptForm(instance=transcript, user=request.user)
        speaker_mapping_form = SpeakerContributorMappingForm(request.POST, **speaker_mapping_context)
        if speaker_mapping_form.is_valid():
            if transcript.rewrite_speaker_labels(speaker_mapping_form.speaker_mapping):
                messages.success(request, _("Speaker labels updated."))
            else:
                messages.warning(request, _("No speaker labels were changed."))
            return redirect("cast-transcript:edit", transcript_id=transcript.id)
        messages.error(request, _("The speaker labels could not be updated due to errors."))
    elif request.method == "POST":
        speaker_mapping_form = SpeakerContributorMappingForm(**speaker_mapping_context)
        form = TranscriptForm(request.POST, request.FILES, instance=transcript, user=request.user)
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
        form = TranscriptForm(instance=transcript, user=request.user)
        speaker_mapping_form = SpeakerContributorMappingForm(**speaker_mapping_context)
    if known_speaker_review_form is None:
        known_speaker_review_form = KnownSpeakerSegmentReviewForm(
            segments=transcript.get_speaker_suggestions(),
            contributor_assignments=speaker_mapping_context["contributor_assignments"],
            multiple_episodes=speaker_mapping_context["multiple_episodes"],
        )
    speaker_mapping_rows = get_speaker_mapping_rows(
        speaker_mapping_form,
        transcript.get_speaker_samples(),
    )
    known_speaker_review_rows = get_known_speaker_review_rows(transcript, known_speaker_review_form)
    voice_reference_candidate_groups = get_voice_reference_candidate_groups(transcript, speaker_mapping_context)

    return render(
        request,
        "cast/transcript/edit.html",
        {
            "transcript": transcript,
            "form": form,
            "speaker_mapping_rows": speaker_mapping_rows,
            "speaker_mapping_form": speaker_mapping_form,
            "speaker_labels": speaker_mapping_context["speaker_labels"],
            "transcript_audio_sources": get_transcript_audio_sources(transcript),
            "contributor_assignments": speaker_mapping_context["contributor_assignments"],
            "voice_reference_candidate_groups": voice_reference_candidate_groups,
            "known_speaker_review": transcript.known_speaker_review_summary(),
            "known_speaker_review_form": known_speaker_review_form,
            "known_speaker_review_rows": known_speaker_review_rows,
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

    upload_form = TranscriptForm(prefix="media-chooser-upload", user=request.user)

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
        form = TranscriptForm(
            request.POST, request.FILES, instance=transcript, user=request.user, prefix="media-chooser-upload"
        )

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
        "uploadform": TranscriptForm(user=request.user),
        "is_searching": False,
        "pagination_template": "wagtailadmin/shared/pagination_nav.html",
    }
    return render_modal_workflow(
        request,
        "cast/transcript/chooser_chooser.html",
        None,
        context,
        json_data={"step": "chooser"},
    )


def podlove_transcript_json(request: HttpRequest, pk) -> HttpResponse:
    """Return the podlove transcript content as JSON because of CORS restrictions."""
    transcript = get_object_or_404(Transcript, pk=pk)
    if transcript.podlove:
        # Open the file and load its contents as JSON
        with transcript.podlove.open("r") as file:
            try:
                data = json.load(file)  # assumes the file content is JSON
            except json.JSONDecodeError:
                return HttpResponse("Invalid JSON format in podlove file", status=400)
        episode = public_episode_from_request(request, transcript=transcript)
        data = sanitize_podlove_data(data, strict_public_speaker_labels_for_transcript(transcript, episode=episode))
        return JsonResponse(data)
    return HttpResponse("Podlove file not available", status=404)


def podcastindex_transcript_json(request: HttpRequest, pk: int) -> HttpResponse:
    """Return the podcastindex transcript content as JSON because of CORS restrictions."""
    transcript = get_object_or_404(Transcript, pk=pk)
    if not transcript.dote:
        return HttpResponse("podcastindex JSON file not available", status=404)
    try:
        episode = public_episode_from_request(request, transcript=transcript)
        with transcript.dote.open("r") as file:
            dote_data = json.load(file)
        if not dote_data:
            return JsonResponse(dote_data)
        dote_data = sanitize_dote_data(
            dote_data,
            strict_public_speaker_labels_for_transcript(transcript, episode=episode),
        )
        return JsonResponse(convert_dote_to_podcastindex_transcript(dote_data))
    except (FileNotFoundError, OSError):
        return HttpResponse("podcastindex JSON file missing", status=404)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON format in dote file", status=400)


def webvtt_transcript(request: HttpRequest, pk: int) -> HttpResponse:
    """Return the transcript content as WebVTT because of CORS restrictions."""
    transcript = get_object_or_404(Transcript, pk=pk)
    if transcript.vtt:
        # Open the file and return its contents as WebVTT
        with transcript.vtt.open("r") as file:
            content = file.read()
        episode = public_episode_from_request(request, transcript=transcript)
        content = sanitize_webvtt_content(
            content,
            strict_public_speaker_labels_for_transcript(transcript, episode=episode),
        )
        return HttpResponse(content, content_type="text/vtt")
    return HttpResponse("WebVTT file not available", status=404)


def episode_transcript(request: HtmxHttpRequest, blog_slug: str, episode_slug: str) -> HttpResponse:
    blog = get_site_specific_page_or_404(Blog, request, slug=blog_slug)
    episode = get_object_or_404(Episode.objects.descendant_of(blog), slug=episode_slug, live=True)
    transcript = episode.get_transcript_or_none()
    if transcript is None:
        raise Http404("Transcript not found")
    base_template_dir = episode.get_template_base_dir(request)
    return _render_transcript_html(request, transcript, base_template_dir, episode=episode)


def html_transcript(request: HtmxHttpRequest, transcript_pk: int, post_pk: int | None = None) -> HttpResponse:
    """Return the transcript content as HTML."""
    transcript = get_object_or_404(Transcript, pk=transcript_pk)
    post: Post | None = None
    if post_pk is not None:
        post = get_object_or_404(Post, pk=post_pk)
        post = post.specific
        if isinstance(post, Episode) and post.transcript and post.transcript.pk == transcript.pk:
            return redirect(post.get_transcript_url())
        base_template_dir = post.get_template_base_dir(request)
    else:
        base_template_dir = get_template_base_dir(request, pre_selected=None)
    episode = post if isinstance(post, Episode) else None
    return _render_transcript_html(request, transcript, base_template_dir, episode=episode)
