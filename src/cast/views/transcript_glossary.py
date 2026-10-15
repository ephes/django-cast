"""Glossary review on the transcript edit view.

Shows the corrections sidecar (``cast.transcripts.corrections``) as a summary,
one row per proposal group and a list of the replacements in effect, and handles
the review actions posted from it. Every action redirects back to the edit view.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from django import forms
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.html import format_html
from django.utils.safestring import SafeString
from django.utils.translation import gettext_lazy as _, ngettext
from wagtail.admin import messages

from ..forms import (
    GlossaryAddForm,
    GlossaryEpisodeForm,
    GlossaryGroupDecisionForm,
    GlossaryOccurrenceDecisionForm,
    GlossaryReplacementRejectForm,
)
from ..models import Episode, Transcript
from ..transcripts import corrections, editing, parsing
from ..transcripts.corrections import STATE_APPROVED, STATE_AUTO, STATE_OPEN, STATE_REJECTED, CorrectionsResult
from ..transcripts.glossary import normalize_phrase

CONTEXT_CHARS = 80
GROUP_SAMPLES = 3
GLOSSARY_EDIT_PERMISSIONS = (
    "cast.add_transcriptglossaryterm",
    "cast.change_transcriptglossaryterm",
    "cast.change_contributor",
)


class GlossaryOccurrence(TypedDict):
    context: SafeString
    end: int
    end_seconds: float | None
    original: str
    source: str
    start: int
    start_ms: int
    start_seconds: float
    state: str
    timestamp_label: str
    to: str


class GlossaryOriginal(TypedDict):
    count: int
    original: str


class GlossaryGroup(TypedDict):
    occurrences: list[GlossaryOccurrence]
    originals: list[GlossaryOriginal]
    samples: list[GlossaryOccurrence]
    to: str


@dataclass
class GlossaryReview:
    """What the glossary section of the transcript edit view shows."""

    available: bool
    current: bool = False
    needs_episode: bool = False
    stale_episode: bool = False
    episode: Episode | None = None
    episode_form: GlossaryEpisodeForm | None = None
    groups: list[GlossaryGroup] = field(default_factory=list)
    replacements: list[GlossaryOccurrence] = field(default_factory=list)
    rejected: list[GlossaryOccurrence] = field(default_factory=list)
    can_add_to_glossary: bool = False

    @property
    def automatic(self) -> int:
        return sum(item["state"] == STATE_AUTO for item in self.replacements)

    @property
    def approved(self) -> int:
        return sum(item["state"] == STATE_APPROVED for item in self.replacements)

    @property
    def open_proposals(self) -> int:
        return sum(len(group["occurrences"]) for group in self.groups)

    @property
    def summary(self) -> str:
        automatic = ngettext("%(count)d automatic replacement", "%(count)d automatic replacements", self.automatic) % {
            "count": self.automatic
        }
        approved = ngettext("%(count)d approved replacement", "%(count)d approved replacements", self.approved) % {
            "count": self.approved
        }
        groups = ngettext("%(count)d open proposal group", "%(count)d open proposal groups", len(self.groups)) % {
            "count": len(self.groups)
        }
        occurrences = ngettext(
            "%(count)d occurrence left to decide", "%(count)d occurrences left to decide", self.open_proposals
        ) % {"count": self.open_proposals}
        return str(
            _("{automatic} and {approved}; {groups} with {occurrences}.").format(
                automatic=automatic, approved=approved, groups=groups, occurrences=occurrences
            )
        )


def marked_context(text: str, start: int, end: int, *, chars: int = CONTEXT_CHARS) -> SafeString:
    """Text around ``text[start:end]``, escaped, with the span in ``<mark>``."""
    before = text[:start]
    if len(before) > chars:
        before = before[-chars:]
        space = before.find(" ")
        before = "…" + (before[space + 1 :] if space != -1 else before)
    after = text[end:]
    if len(after) > chars:
        after = after[:chars]
        space = after.rfind(" ")
        after = (after[:space] if space > 0 else after) + "…"
    return format_html("{}<mark>{}</mark>{}", before, text[start:end], after)


def user_can_edit_glossary(user: Any) -> bool:
    """Adding to the glossary edits show terms or contributors, so it needs their snippet permissions."""
    return all(user.has_perm(permission) for permission in GLOSSARY_EDIT_PERMISSIONS)


def _occurrence(
    segment: dict[str, Any], next_start_ms: int | None, item: dict[str, Any], original: str
) -> GlossaryOccurrence:
    start_seconds = segment["start_ms"] / 1000
    return {
        "context": marked_context(segment["raw_text"], item["start"], item["end"]),
        "end": item["end"],
        "end_seconds": next_start_ms / 1000 if next_start_ms is not None else None,
        "original": original,
        "source": item["source"],
        "start": item["start"],
        "start_ms": segment["start_ms"],
        "start_seconds": start_seconds,
        "state": item["state"],
        "timestamp_label": parsing.format_sample_timestamp(start_seconds),
        "to": item["to"],
    }


def get_glossary_review(transcript: Transcript, user: Any) -> GlossaryReview:
    if not transcript.podlove:
        return GlossaryReview(available=False)
    current = corrections.corrections_are_current(transcript)
    state = corrections.corrections_episode_state(transcript)
    review = GlossaryReview(
        available=True,
        current=current,
        needs_episode=state.needs_choice,
        stale_episode=state.stale,
        episode=state.episode,
        episode_form=GlossaryEpisodeForm(transcript=transcript) if state.needs_choice else None,
        can_add_to_glossary=user_can_edit_glossary(user),
    )
    if not current or state.needs_choice:
        return review
    data = transcript.corrections_data
    segments = sorted(data["segments"], key=lambda segment: segment["start_ms"])
    next_starts = {
        segment["start_ms"]: (segments[index + 1]["start_ms"] if index + 1 < len(segments) else None)
        for index, segment in enumerate(segments)
    }
    by_start = {segment["start_ms"]: segment for segment in segments}
    for segment in segments:
        for item in segment["replacements"]:
            occurrence = _occurrence(segment, next_starts[segment["start_ms"]], item, item["from"])
            (review.rejected if item["state"] == STATE_REJECTED else review.replacements).append(occurrence)
    groups: dict[str, GlossaryGroup] = {}
    originals: dict[str, dict[str, GlossaryOriginal]] = {}
    for item in data["proposals"]:
        segment = by_start.get(item["start_ms"])
        if segment is None or item["state"] not in (STATE_OPEN, STATE_REJECTED):
            continue  # approved proposals are listed with the replacements
        occurrence = _occurrence(segment, next_starts[item["start_ms"]], item, item["original"])
        if item["state"] == STATE_REJECTED:
            review.rejected.append(occurrence)
            continue
        group = groups.setdefault(item["to"], {"occurrences": [], "originals": [], "samples": [], "to": item["to"]})
        group["occurrences"].append(occurrence)
        if len(group["samples"]) < GROUP_SAMPLES:
            group["samples"].append(occurrence)
        counted = originals.setdefault(item["to"], {})
        key = normalize_phrase(item["original"])
        if key not in counted:
            counted[key] = {"count": 0, "original": item["original"]}
            group["originals"].append(counted[key])
        counted[key]["count"] += 1
    review.rejected.sort(key=lambda item: (item["start_ms"], item["start"], item["to"]))
    review.groups = sorted(groups.values(), key=lambda group: (-len(group["occurrences"]), group["to"].casefold()))
    return review


# --- actions ---------------------------------------------------------------------------------


def _result_message(request: HttpRequest, result: CorrectionsResult) -> None:
    if result.needs_episode:
        messages.warning(
            request,
            _("Choose the episode whose contributors and podcast form the glossary for this transcript."),
        )
    elif result.status == corrections.STATUS_NO_SEGMENTS:
        messages.warning(request, _("The transcript has no Podlove segments to correct."))
    else:
        messages.success(
            request,
            _(
                "Glossary applied: {automatic} automatic and {approved} approved replacements, "
                "{proposals} open proposals, {changed} segments changed."
            ).format(
                automatic=result.automatic,
                approved=result.approved,
                proposals=result.proposals,
                changed=result.changed,
            ),
        )


def _form_errors(form: forms.Form) -> str:
    return " ".join(str(error) for errors in form.errors.values() for error in errors)


def _run(
    request: HttpRequest,
    transcript: Transcript,
    form: forms.Form | None,
    operation: Callable[[dict[str, Any]], CorrectionsResult],
) -> HttpResponse:
    if form is not None and not form.is_valid():
        messages.error(request, _("The glossary review action was invalid: {0}").format(_form_errors(form)))
    else:
        try:
            result = operation(form.cleaned_data if form is not None else {})
        except ValidationError as error:
            messages.error(request, editing.validation_error_message(error))
        except LookupError:
            messages.error(request, _("That proposal or replacement is no longer available. Reload and try again."))
        except ValueError as error:
            messages.error(request, str(error))
        else:
            _result_message(request, result)
    return redirect("cast-transcript:edit", transcript_id=transcript.id)


def handle_refresh(request: HttpRequest, transcript: Transcript, _context: Any) -> HttpResponse:
    return _run(request, transcript, None, lambda data: corrections.refresh_transcript_corrections(transcript))


def handle_episode(request: HttpRequest, transcript: Transcript, _context: Any) -> HttpResponse:
    form = GlossaryEpisodeForm(request.POST, transcript=transcript)
    return _run(
        request, transcript, form, lambda data: corrections.set_corrections_episode(transcript, data["episode"])
    )


def handle_group(request: HttpRequest, transcript: Transcript, _context: Any) -> HttpResponse:
    form = GlossaryGroupDecisionForm(request.POST)
    return _run(
        request,
        transcript,
        form,
        lambda data: corrections.decide_correction_group(transcript, data["to"], data["decision"]),
    )


def handle_occurrence(request: HttpRequest, transcript: Transcript, _context: Any) -> HttpResponse:
    form = GlossaryOccurrenceDecisionForm(request.POST)
    return _run(
        request,
        transcript,
        form,
        lambda data: corrections.decide_correction_occurrence(
            transcript,
            start_ms=data["start_ms"],
            start=data["start"],
            end=data["end"],
            to=data["to"],
            action=data["decision"],
        ),
    )


def handle_add(request: HttpRequest, transcript: Transcript, _context: Any) -> HttpResponse:
    if not user_can_edit_glossary(request.user):
        messages.error(request, _("You do not have permission to edit the glossary."))
        return redirect("cast-transcript:edit", transcript_id=transcript.id)
    form = GlossaryAddForm(request.POST)
    return _run(
        request,
        transcript,
        form,
        lambda data: corrections.add_original_to_glossary(transcript, data["original"], data["to"]),
    )


def handle_reject_replacement(request: HttpRequest, transcript: Transcript, _context: Any) -> HttpResponse:
    form = GlossaryReplacementRejectForm(request.POST)
    return _run(
        request,
        transcript,
        form,
        lambda data: corrections.reject_automatic_replacement(
            transcript, start_ms=data["start_ms"], start=data["start"], end=data["end"], to=data["to"]
        ),
    )
