import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from django.core.exceptions import ValidationError
from django.forms.boundfield import BoundField
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from wagtail.admin import messages
from wagtail.permission_policies.collections import CollectionPermissionPolicy
from wagtail.search.backends import get_search_backends

from ..forms import (
    KNOWN_SPEAKER_APPLY_ACTION,
    KNOWN_SPEAKER_REVIEW_ACTION,
    KnownSpeakerSegmentReviewForm,
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
    Post,
    Transcript,
    TranscriptSpeakerMapping,
    TranscriptSpeakerSample,
    TranscriptVoiceReferenceCandidate,
    get_template_base_dir,
)
from ..audio_access import authorize_transcript_access, request_may_view_page
from ..models.contributors import ContributorVoiceReference
from ..site_lookup import get_site_specific_page_or_404
from ..transcripts import editing, parsing
from ..transcripts.dote import convert_dote_to_podcastindex_transcript, dote_timestamp_to_ms
from ..transcript_sanitization import (
    apply_public_speaker_mapping_to_dote_data,
    apply_public_speaker_mapping_to_podlove_data,
    apply_public_speaker_mapping_to_webvtt_content,
    public_episode_from_request,
    sanitize_dote_data,
    sanitize_podlove_data,
    sanitize_webvtt_content,
    strict_public_speaker_labels_for_transcript,
)
from . import AuthenticatedHttpRequest, HtmxHttpRequest
from .media import MediaAdminConfig, MediaAdminViews


TRANSCRIPT_FALLBACK_THEME = "plain"
transcript_permission_policy = CollectionPermissionPolicy(Transcript)

create_voice_reference_from_candidate = editing.create_voice_reference_from_candidate
get_speaker_mapping_context = editing.get_speaker_mapping_context
get_voice_reference_candidate = editing.get_voice_reference_candidate
resolve_voice_reference_contributor = editing.resolve_voice_reference_contributor
validation_error_message = editing.validation_error_message


class SpeakerMappingRow(TypedDict):
    display_name_field: BoundField
    mapping: TranscriptSpeakerMapping
    samples: list[TranscriptSpeakerSample]
    target_field: BoundField


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
    data = apply_public_speaker_mapping_to_podlove_data(data, transcript, episode=episode)
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


def _search_transcripts(base_transcripts: Any, raw_query_string: str) -> tuple[Any, str]:
    return base_transcripts.filter(audio__title__icontains=raw_query_string), raw_query_string


def _create_transcript(user: Any) -> Transcript:
    return Transcript()


def _transcript_message_arg(transcript: Transcript) -> Any:
    return transcript.pk


def get_speaker_mapping_rows(
    speaker_mapping_form: SpeakerContributorMappingForm,
    speaker_samples: dict[str, list[TranscriptSpeakerSample]],
) -> list[SpeakerMappingRow]:
    return [
        {
            "display_name_field": speaker_mapping_form[f"speaker_display_name_{index}"],
            "mapping": speaker_mapping_form.mapping_by_label[speaker_label],
            "samples": speaker_samples.get(speaker_label, []),
            "target_field": speaker_mapping_form[field_name],
        }
        for index, (field_name, speaker_label) in enumerate(speaker_mapping_form.speaker_field_names.items())
        if speaker_label in speaker_mapping_form.mapping_by_label
    ]


def get_known_speaker_text_by_start_ms(transcript: Transcript) -> dict[int, str]:
    texts: dict[int, str] = {}
    podlove_segments = transcript.podlove_data.get("transcripts", [])
    if isinstance(podlove_segments, list):
        for segment in podlove_segments:
            if not isinstance(segment, dict):
                continue
            start_ms = segment.get("start_ms")
            text = parsing.clean_sample_text(segment.get("text"))
            if isinstance(start_ms, int) and text:
                texts.setdefault(start_ms, text)
    dote_lines = transcript.dote_data.get("lines", [])
    if isinstance(dote_lines, list):
        for line in dote_lines:
            if not isinstance(line, dict):
                continue
            start_ms = dote_timestamp_to_ms(line.get("startTime"))
            text = parsing.clean_sample_text(line.get("text"))
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
        start_seconds = parsing.parse_timestamp_seconds(segment.get("start"))
        start_ms = int(round(start_seconds * 1000)) if start_seconds is not None else None
        text = parsing.clean_sample_text(segment.get("text"))
        if not text and start_ms is not None:
            text = text_by_start_ms.get(start_ms, "")
        rows.append(
            {
                "confidence": segment.get("confidence"),
                "field": known_speaker_review_form[field_name],
                "margin": segment.get("margin"),
                "speaker": parsing.clean_speaker_label(segment.get("speaker")),
                "text": parsing.truncate_sample_text(text, max_chars=140) if text else "",
                "timestamp_label": parsing.format_sample_timestamp(start_seconds),
                "uncertain": bool(segment.get("speaker_uncertain") or segment.get("low_margin")),
            }
        )
    return rows


def get_voice_reference_candidate_groups(
    transcript: Transcript,
    speaker_mapping_context: editing.SpeakerMappingContext,
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
            editing.get_duplicate_voice_reference(transcript=transcript, contributor=contributor, candidate=candidate)
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


@dataclass
class EditFormState:
    form: TranscriptForm
    speaker_mapping_form: SpeakerContributorMappingForm
    known_speaker_review_form: KnownSpeakerSegmentReviewForm | None = None


EditActionHandler = Callable[[HttpRequest, Transcript, editing.SpeakerMappingContext], HttpResponse | EditFormState]


def _handle_known_speaker_apply(
    request: HttpRequest,
    transcript: Transcript,
    speaker_mapping_context: editing.SpeakerMappingContext,
) -> HttpResponse | EditFormState:
    applied = transcript.apply_known_speaker_suggestions()
    if applied:
        messages.success(
            request,
            _("Applied known-speaker names to {0} public transcript entries.").format(applied),
        )
    else:
        messages.warning(request, _("No confident known-speaker suggestions were available to apply."))
    return redirect("cast-transcript:edit", transcript_id=transcript.id)


def _handle_known_speaker_review(
    request: HttpRequest,
    transcript: Transcript,
    speaker_mapping_context: editing.SpeakerMappingContext,
) -> HttpResponse | EditFormState:
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
                _("Saved known-speaker segment decisions and applied {0} public transcript entries.").format(applied),
            )
        else:
            messages.warning(request, _("No known-speaker segment decisions were changed."))
        return redirect("cast-transcript:edit", transcript_id=transcript.id)
    messages.error(request, _("The known-speaker segment decisions could not be saved due to errors."))
    return EditFormState(
        form=form,
        speaker_mapping_form=speaker_mapping_form,
        known_speaker_review_form=known_speaker_review_form,
    )


def _handle_voice_reference_create(
    request: HttpRequest,
    transcript: Transcript,
    speaker_mapping_context: editing.SpeakerMappingContext,
) -> HttpResponse | EditFormState:
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
    return EditFormState(form=form, speaker_mapping_form=speaker_mapping_form)


def _handle_speaker_mapping_save(
    request: HttpRequest,
    transcript: Transcript,
    speaker_mapping_context: editing.SpeakerMappingContext,
) -> HttpResponse | EditFormState:
    form = TranscriptForm(instance=transcript, user=request.user)
    speaker_mapping_form = SpeakerContributorMappingForm(request.POST, **speaker_mapping_context)
    if speaker_mapping_form.is_valid():
        if speaker_mapping_form.save():
            messages.success(request, _("Speaker mappings saved."))
        else:
            messages.warning(request, _("No speaker mappings were changed."))
        return redirect("cast-transcript:edit", transcript_id=transcript.id)
    messages.error(request, _("The speaker labels could not be updated due to errors."))
    return EditFormState(form=form, speaker_mapping_form=speaker_mapping_form)


def _handle_transcript_form_save(
    request: HttpRequest,
    transcript: Transcript,
    speaker_mapping_context: editing.SpeakerMappingContext,
) -> HttpResponse | EditFormState:
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
    return EditFormState(form=form, speaker_mapping_form=speaker_mapping_form)


EDIT_ACTION_HANDLERS: dict[str, EditActionHandler] = {
    KNOWN_SPEAKER_APPLY_ACTION: _handle_known_speaker_apply,
    KNOWN_SPEAKER_REVIEW_ACTION: _handle_known_speaker_review,
    VOICE_REFERENCE_CREATE_ACTION: _handle_voice_reference_create,
    SPEAKER_MAPPING_ACTION: _handle_speaker_mapping_save,
}


def edit(request: HttpRequest, transcript_id: int) -> HttpResponse:
    transcript = get_object_or_404(
        transcript_permission_policy.instances_user_has_permission_for(request.user, "change"),
        id=transcript_id,
    )
    speaker_mapping_context = editing.get_speaker_mapping_context(transcript)

    if request.method == "POST":
        handler = EDIT_ACTION_HANDLERS.get(cast(str, request.POST.get("action")), _handle_transcript_form_save)
        result = handler(request, transcript, speaker_mapping_context)
        if isinstance(result, HttpResponse):
            return result
        form_state = result
    else:
        form_state = EditFormState(
            form=TranscriptForm(instance=transcript, user=request.user),
            speaker_mapping_form=SpeakerContributorMappingForm(**speaker_mapping_context),
        )
    form = form_state.form
    speaker_mapping_form = form_state.speaker_mapping_form
    known_speaker_review_form = form_state.known_speaker_review_form
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
            "user_can_delete": transcript_permission_policy.user_has_permission_for_instance(
                request.user, "delete", transcript
            ),
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


transcript_admin_config = MediaAdminConfig(
    model=Transcript,
    permission_policy=transcript_permission_policy,
    get_form=lambda: TranscriptForm,
    url_namespace="cast-transcript",
    template_dir="cast/transcript",
    plural_context_name="transcripts",
    singular_context_name="transcript",
    chosen_step="transcript_chosen",
    get_chosen_data=get_transcript_data,
    create_instance=_create_transcript,
    search=_search_transcripts,
    ordering=None,
    show_popular_tags=False,
    index_search_placeholder=_("Search transcript files"),
    index_fallback_placeholder=_("Search transcripts"),
    added_message=_("Transcript file '{0}' added."),
    add_error_message=_("The transcript file could not be saved due to errors."),
    deleted_message=_("Transcript '{0}' deleted."),
    chooser_upload_error_message=_("The transcript could not be saved due to errors."),
    message_arg=_transcript_message_arg,
)

_views = MediaAdminViews(transcript_admin_config)

index = _views.index
chooser = _views.chooser


def add(request: AuthenticatedHttpRequest) -> HttpResponse:
    return _views.add(request)


def delete(request: HttpRequest, transcript_id: int) -> HttpResponse:
    return _views.delete(request, transcript_id)


def chosen(request: HttpRequest, transcript_id: int) -> HttpResponse:
    return _views.chosen(request, transcript_id)


def chooser_upload(request: AuthenticatedHttpRequest) -> HttpResponse:
    return _views.chooser_upload(request)


def podlove_transcript_json(request: HttpRequest, pk: int) -> HttpResponse:
    """Return the podlove transcript content as JSON because of CORS restrictions."""
    transcript = get_object_or_404(Transcript, pk=pk)
    authorize_transcript_access(request, transcript=transcript, explicit_anchor_id=request.GET.get("episode_id"))
    if transcript.podlove:
        # Open the file and load its contents as JSON
        with transcript.podlove.open("r") as file:
            try:
                data = json.load(file)  # assumes the file content is JSON
            except json.JSONDecodeError:
                return HttpResponse("Invalid JSON format in podlove file", status=400)
        episode = public_episode_from_request(request, transcript=transcript)
        data = apply_public_speaker_mapping_to_podlove_data(data, transcript, episode=episode)
        data = sanitize_podlove_data(data, strict_public_speaker_labels_for_transcript(transcript, episode=episode))
        return JsonResponse(data)
    return HttpResponse("Podlove file not available", status=404)


def podcastindex_transcript_json(request: HttpRequest, pk: int) -> HttpResponse:
    """Return the podcastindex transcript content as JSON because of CORS restrictions."""
    transcript = get_object_or_404(Transcript, pk=pk)
    authorize_transcript_access(request, transcript=transcript, explicit_anchor_id=request.GET.get("episode_id"))
    if not transcript.dote:
        return HttpResponse("podcastindex JSON file not available", status=404)
    try:
        episode = public_episode_from_request(request, transcript=transcript)
        with transcript.dote.open("r") as file:
            dote_data = json.load(file)
        if not dote_data:
            return JsonResponse(dote_data)
        dote_data = apply_public_speaker_mapping_to_dote_data(dote_data, transcript, episode=episode)
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
    authorize_transcript_access(request, transcript=transcript, explicit_anchor_id=request.GET.get("episode_id"))
    if transcript.vtt:
        # Open the file and return its contents as WebVTT
        with transcript.vtt.open("r") as file:
            content = file.read()
        episode = public_episode_from_request(request, transcript=transcript)
        content = apply_public_speaker_mapping_to_webvtt_content(content, transcript, episode=episode)
        content = sanitize_webvtt_content(
            content,
            strict_public_speaker_labels_for_transcript(transcript, episode=episode),
        )
        return HttpResponse(content, content_type="text/vtt")
    return HttpResponse("WebVTT file not available", status=404)


def episode_transcript(request: HtmxHttpRequest, blog_slug: str, episode_slug: str) -> HttpResponse:
    blog = get_site_specific_page_or_404(Blog, request, slug=blog_slug)
    episode = get_object_or_404(Episode.objects.descendant_of(blog), slug=episode_slug, live=True)
    if not request_may_view_page(episode, request):
        raise Http404("Transcript not found")
    transcript = episode.get_transcript_or_none()
    if transcript is None:
        raise Http404("Transcript not found")
    base_template_dir = episode.get_template_base_dir(request)
    return _render_transcript_html(request, transcript, base_template_dir, episode=episode)


def html_transcript(request: HtmxHttpRequest, transcript_pk: int, post_pk: int | None = None) -> HttpResponse:
    """Return the transcript content as HTML."""
    transcript = get_object_or_404(Transcript, pk=transcript_pk)
    authorize_transcript_access(request, transcript=transcript, explicit_anchor_id=post_pk)
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
