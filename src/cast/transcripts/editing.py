"""Transcript editor orchestration helpers that operate on model instances."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.translation import gettext_lazy as _

from ..models import (
    Audio,
    Contributor,
    Episode,
    EpisodeContributor,
    Transcript,
    TranscriptSpeakerMapping,
    TranscriptVoiceReferenceCandidate,
)
from ..models.contributors import ContributorVoiceReference
from .services import artifact_revision


class SpeakerMappingContext(TypedDict):
    contributor_assignments: list[EpisodeContributor]
    multiple_episodes: bool
    speaker_mappings: list[TranscriptSpeakerMapping]
    speaker_labels: list[str]
    source_episode: Episode | None


def episode_from_latest_revision(episode: Episode) -> Episode:
    return cast(Episode, episode.get_latest_revision_as_object())


def get_speaker_mapping_context(transcript: Transcript) -> SpeakerMappingContext:
    transcript.sync_speaker_mappings()
    episodes = [
        episode_from_latest_revision(episode)
        for episode in transcript.audio.episodes.select_related("latest_revision")
        .prefetch_related("contributor_assignments__contributor")
        .all()
    ]
    contributor_assignments: list[EpisodeContributor] = []
    for episode in episodes:
        contributor_assignments.extend(episode.visible_contributor_assignments)
    speaker_mappings = list(transcript.speaker_mappings.select_related("contributor").all())
    speaker_labels = [mapping.speaker_label for mapping in speaker_mappings if mapping.active]
    return {
        "contributor_assignments": contributor_assignments,
        "multiple_episodes": len(episodes) > 1,
        "speaker_mappings": speaker_mappings,
        "speaker_labels": speaker_labels,
        "source_episode": episodes[0] if len(episodes) == 1 else None,
    }


def resolve_voice_reference_contributor(
    speaker_label: str,
    contributor_assignments: list[EpisodeContributor],
    speaker_mappings: list[TranscriptSpeakerMapping] | tuple[()] = (),
    *,
    mapping_fingerprint: str | None = None,
) -> Contributor | None:
    mapped_ids = {
        mapping.contributor_id
        for mapping in speaker_mappings
        if mapping.speaker_label == speaker_label
        and mapping.active
        and mapping.review_state == TranscriptSpeakerMapping.ReviewState.APPROVED
        and mapping.source_artifact_fingerprint
        == (mapping.transcript.mapping_fingerprint() if mapping_fingerprint is None else mapping_fingerprint)
        and mapping.contributor_id is not None
    }
    contributors: dict[int, Contributor] = {}
    for assignment in contributor_assignments:
        if (
            assignment.display_name != speaker_label and assignment.contributor_id not in mapped_ids
        ) or assignment.contributor_id is None:
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


CANDIDATE_SIGNING_SALT = "cast.voice-reference-candidate"


def transcript_evidence(transcript: Transcript, *, enforce_byte_budget: bool = True) -> dict[str, Any]:
    """Per-transcript part of the signed evidence; reads every artifact once.

    Regeneration consent passes ``enforce_byte_budget=False``: replacing an
    oversized transcript must stay possible, so it hashes the complete files
    like the storage paths do.
    """
    return {
        "transcript": transcript.pk,
        "revision": artifact_revision(transcript),
        "fingerprint": transcript.transcript_artifact_fingerprint(enforce_byte_budget=enforce_byte_budget),
        # Stored audio names are immutable upload generations. Include every
        # format because a reference can be auditioned using any offered source.
        "audio": {
            "id": transcript.audio_id,
            "files": {name: getattr(transcript.audio, name).name or "" for name in Audio.audio_formats},
            "duration": str(transcript.audio.duration),
        },
    }


def candidate_evidence(
    transcript_part: dict[str, Any], candidate: TranscriptVoiceReferenceCandidate, contributor: Contributor | None
) -> dict[str, Any]:
    return {
        **transcript_part,
        "contributor": contributor.pk if contributor is not None else None,
        "speaker": candidate.speaker_label,
        "rank": candidate.rank,
        "start": str(candidate.start_seconds),
        "end": str(candidate.end_seconds),
        "duration": str(candidate.duration_seconds),
        "text": candidate.text,
    }


def sign_voice_reference_candidate(
    transcript_part: dict[str, Any], candidate: TranscriptVoiceReferenceCandidate, contributor: Contributor | None
) -> str:
    return signing.dumps(candidate_evidence(transcript_part, candidate, contributor), salt=CANDIDATE_SIGNING_SALT)


def create_voice_reference_from_candidate(
    transcript: Transcript,
    speaker_mapping_context: SpeakerMappingContext,
    candidate: TranscriptVoiceReferenceCandidate,
    *,
    status: str,
    consent_confirmed: bool,
    candidate_token: str | None = None,
) -> tuple[ContributorVoiceReference, bool]:
    using = router.db_for_write(ContributorVoiceReference, instance=transcript)
    with transaction.atomic(using=using):
        # Obtain the write lock before reading, including on SQLite. Audio
        # owns the duplicate source-range key. Also lock the transcript
        # generation before checking the signed evidence.
        Audio.objects.using(using).filter(pk=transcript.audio_id).update(title=models.F("title"))
        Transcript.objects.using(using).filter(pk=transcript.pk).update(
            source_fingerprint=models.F("source_fingerprint")
        )
        transcript = Transcript.objects.using(using).get(pk=transcript.pk)
        if candidate_token is not None:
            speaker_mapping_context = get_speaker_mapping_context(transcript)
        contributor = resolve_voice_reference_contributor(
            candidate.speaker_label,
            speaker_mapping_context["contributor_assignments"],
            speaker_mapping_context["speaker_mappings"],
        )
        if contributor is None:
            raise ValidationError(
                _("Map this speaker label to one episode contributor before creating a voice reference.")
            )
        current_candidate = get_voice_reference_candidate(
            transcript, speaker_label=candidate.speaker_label, candidate_rank=candidate.rank
        )
        if current_candidate != candidate:
            raise ValidationError(_("Voice-reference evidence changed. Reload the transcript and review it again."))
        if candidate_token is not None:
            try:
                evidence = signing.loads(candidate_token, salt=CANDIDATE_SIGNING_SALT)
            except signing.BadSignature as error:
                raise ValidationError(_("Invalid voice-reference choice. Reload the transcript.")) from error
            if evidence != candidate_evidence(transcript_evidence(transcript), candidate, contributor):
                raise ValidationError(
                    _("Voice-reference evidence changed. Reload the transcript and review it again.")
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
