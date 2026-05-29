from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from cast.devdata import create_transcript
from cast.forms import VoiceReferenceCandidateCreateForm
from cast.models import Contributor, EpisodeContributor, TranscriptVoiceReferenceCandidate
from cast.models.contributors import ContributorVoiceReference
from cast.models.transcript import Transcript
from cast.views.transcript import (
    create_voice_reference_from_candidate,
    get_speaker_mapping_context,
    get_voice_reference_candidate,
    get_voice_reference_candidate_groups,
    resolve_voice_reference_contributor,
    validation_error_message,
)


def podlove_segment(
    speaker: str,
    start: str,
    end: str,
    *,
    text: str | None = None,
    voice: str | None = None,
) -> dict:
    return {
        "speaker": speaker,
        "voice": speaker if voice is None else voice,
        "start_ms": int(Decimal(start) * 1000),
        "end_ms": int(Decimal(end) * 1000),
        "text": text if text is not None else f"{speaker} says enough useful words for a candidate range.",
    }


@pytest.mark.django_db
class TestVoiceReferenceCandidateDerivation:
    def test_derives_ranked_capped_candidates_from_contiguous_speaker_runs(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    podlove_segment("Alice", "0", "10", text="Alice first clean sentence."),
                    podlove_segment("Alice", "10", "25", text="Alice continues cleanly."),
                    podlove_segment("Bob", "25", "29", text="Bob short."),
                    podlove_segment("Alice", "30", "70", text="Alice has a long clean run."),
                    podlove_segment("Bob", "75", "85", text="Bob has a long enough fallback."),
                ]
            },
        )

        candidates = transcript.get_voice_reference_candidates(limit_per_speaker=2)

        assert [
            (candidate.speaker_label, candidate.start_seconds, candidate.end_seconds, candidate.duration_seconds)
            for candidate in candidates
        ] == [
            ("Alice", Decimal("30.000"), Decimal("60.000"), Decimal("30.000")),
            ("Alice", Decimal("0.000"), Decimal("25.000"), Decimal("25.000")),
            ("Bob", Decimal("75.000"), Decimal("85.000"), Decimal("10.000")),
        ]
        assert [candidate.rank for candidate in candidates] == [1, 2, 1]
        assert candidates[0].start_timestamp_label == "00:30.000"
        assert candidates[0].end_timestamp_label == "01:00.000"
        assert candidates[0].duration_label == "00:30.000"

    def test_derivation_skips_missing_short_multi_label_and_empty_text_segments(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    "not-a-segment",
                    {"speaker": "Alice", "voice": "Alice", "start_ms": 0, "text": "Missing end."},
                    podlove_segment("Alice", "1", "3"),
                    podlove_segment("Alice", "3", "15", voice="Bob"),
                    podlove_segment("Alice", "15", "30", text=""),
                    podlove_segment("Alice", "30", "29"),
                ]
            },
        )

        assert transcript.get_voice_reference_candidates() == []

    def test_derivation_uses_timestamp_strings_and_does_not_mutate_transcript_files(self, audio):
        podlove = {
            "transcripts": [
                {
                    "speaker": "Speaker 1",
                    "voice": "Speaker 1",
                    "start": "00:00:01.500",
                    "end": "00:00:11.750",
                    "text": "A useful sentence with timestamp strings.",
                }
            ]
        }
        transcript = create_transcript(audio=audio, podlove=podlove)

        candidates = transcript.get_voice_reference_candidates()

        assert [(candidate.start_seconds, candidate.end_seconds) for candidate in candidates] == [
            (Decimal("1.500"), Decimal("11.750"))
        ]
        assert transcript.podlove_data == podlove

    def test_candidate_limits_and_invalid_thresholds_return_empty_lists(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={"transcripts": [podlove_segment("Alice", "0", "12")]},
        )

        assert transcript.get_voice_reference_candidates(limit_per_speaker=0) == []
        assert transcript.get_voice_reference_candidates(target_seconds=Decimal("0")) == []

    def test_private_empty_run_builder_guard(self):
        assert (
            Transcript._build_voice_reference_candidate_from_run(
                [],
                target_seconds=Decimal("30.000"),
                min_seconds=Decimal("8.000"),
            )
            is None
        )

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, None),
            (12.25, Decimal("12.250")),
            (object(), None),
            ("", None),
            ("01:02", Decimal("62.000")),
            ("01:02:03.456", Decimal("3723.456")),
            ("5", Decimal("5.000")),
            ("01:02:03:04", None),
            ("not-a-time", None),
        ],
    )
    def test_timestamp_decimal_parser_edges(self, value, expected):
        assert Transcript._parse_timestamp_decimal_seconds(value) == expected

    def test_timestamp_label_formats_hours(self):
        candidate = TranscriptVoiceReferenceCandidate(
            speaker_label="Alice",
            start_seconds=Decimal("3723.456"),
            end_seconds=Decimal("3733.456"),
            duration_seconds=Decimal("10.000"),
            text="Long running episode.",
            rank=1,
        )

        assert candidate.start_timestamp_label == "01:02:03.456"


@pytest.mark.django_db
class TestVoiceReferenceCandidateAdmin:
    def test_edit_page_renders_candidate_rows_with_bounded_audition_data(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="candidate-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Alice", "1.5", "12.5")]},
        )

        response = admin_client.get(reverse("cast-transcript:edit", args=(transcript.pk,)))

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Voice-reference candidates" in content
        assert "Alice" in content
        assert 'data-cast-speaker-seek="1.500"' in content
        assert 'data-cast-speaker-end="12.500"' in content
        assert "Create approved" in content

    def test_post_create_approved_candidate_requires_explicit_consent(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="approved-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Alice", "1", "12")]},
        )

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.pk,)),
            {
                "action": "create-voice-reference",
                "speaker_label": "Alice",
                "candidate_rank": "1",
                "voice_reference_status": "approved",
            },
        )

        assert response.status_code == 200
        assert ContributorVoiceReference.objects.count() == 0
        assert response.context["message"] == "The voice reference could not be created due to errors."

    def test_post_create_approved_candidate_creates_source_range_reference(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="create-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Alice", "1", "12")]},
        )

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.pk,)),
            {
                "action": "create-voice-reference",
                "speaker_label": "Alice",
                "candidate_rank": "1",
                "voice_reference_status": "approved",
                "consent_confirmed": "on",
            },
        )

        assert response.status_code == 302
        reference = ContributorVoiceReference.objects.get()
        assert reference.contributor == contributor
        assert reference.source_audio == transcript.audio
        assert reference.source_episode == episode
        assert reference.start_seconds == Decimal("1.000")
        assert reference.end_seconds == Decimal("12.000")
        assert reference.status == ContributorVoiceReference.Status.APPROVED
        assert reference.consent_confirmed is True

    def test_post_create_pending_candidate_without_consent(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="pending-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Alice", "1", "12")]},
        )

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.pk,)),
            {
                "action": "create-voice-reference",
                "speaker_label": "Alice",
                "candidate_rank": "1",
                "voice_reference_status": "pending",
            },
        )

        assert response.status_code == 302
        reference = ContributorVoiceReference.objects.get()
        assert reference.status == ContributorVoiceReference.Status.PENDING
        assert reference.consent_confirmed is False

    def test_post_duplicate_candidate_keeps_existing_reference(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="duplicate-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Alice", "1", "12")]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        for _ in range(2):
            response = admin_client.post(
                edit_url,
                {
                    "action": "create-voice-reference",
                    "speaker_label": "Alice",
                    "candidate_rank": "1",
                    "voice_reference_status": "pending",
                },
            )
            assert response.status_code == 302

        assert ContributorVoiceReference.objects.count() == 1

    def test_post_missing_candidate_is_rejected(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="missing-candidate-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Alice", "1", "12")]},
        )

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.pk,)),
            {
                "action": "create-voice-reference",
                "speaker_label": "Alice",
                "candidate_rank": "99",
                "voice_reference_status": "pending",
            },
        )

        assert response.status_code == 200
        assert ContributorVoiceReference.objects.count() == 0
        assert response.context["message"] == "The selected voice-reference candidate is no longer available."

    def test_post_unresolved_candidate_is_rejected(self, admin_client, episode):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Speaker 1", "1", "12")]},
        )

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.pk,)),
            {
                "action": "create-voice-reference",
                "speaker_label": "Speaker 1",
                "candidate_rank": "1",
                "voice_reference_status": "pending",
            },
        )

        assert response.status_code == 200
        assert ContributorVoiceReference.objects.count() == 0
        assert (
            response.context["message"]
            == "Map this speaker label to one episode contributor before creating a voice reference."
        )

    def test_source_episode_is_omitted_for_audio_reused_by_multiple_episodes(
        self, admin_client, episode, podcast_episode_with_same_audio
    ):
        contributor = Contributor.objects.create(display_name="Alice", slug="shared-audio-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        EpisodeContributor.objects.create(
            episode=podcast_episode_with_same_audio,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Alice", "1", "12")]},
        )

        response = admin_client.post(
            reverse("cast-transcript:edit", args=(transcript.pk,)),
            {
                "action": "create-voice-reference",
                "speaker_label": "Alice",
                "candidate_rank": "1",
                "voice_reference_status": "pending",
            },
        )

        assert response.status_code == 302
        assert ContributorVoiceReference.objects.get().source_episode is None


@pytest.mark.django_db
class TestVoiceReferenceCandidateHelpers:
    def test_resolve_contributor_handles_missing_and_ambiguous_labels(self, episode):
        first = Contributor.objects.create(display_name="Alex", slug="alex-one")
        second = Contributor.objects.create(display_name="Alex", slug="alex-two")
        first_assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=first,
            role=EpisodeContributor.ROLE_HOST,
        )
        second_assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=second,
            role=EpisodeContributor.ROLE_GUEST,
        )

        assert resolve_voice_reference_contributor("Missing", [first_assignment]) is None
        assert resolve_voice_reference_contributor("Alex", [first_assignment, second_assignment]) is None
        assert resolve_voice_reference_contributor("Alex", [first_assignment]) == first

    def test_candidate_lookup_and_group_context_include_duplicates_and_unresolved_rows(self, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="helper-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    podlove_segment("Alice", "1", "12"),
                    podlove_segment("Speaker 2", "20", "32"),
                ]
            },
        )
        candidate = get_voice_reference_candidate(transcript, speaker_label="Alice", candidate_rank=1)
        assert candidate is not None
        ContributorVoiceReference.objects.create(
            contributor=contributor,
            source_audio=transcript.audio,
            start_seconds=candidate.start_seconds,
            end_seconds=candidate.end_seconds,
        )

        groups = get_voice_reference_candidate_groups(transcript, get_speaker_mapping_context(transcript))

        assert get_voice_reference_candidate(transcript, speaker_label="Alice", candidate_rank=99) is None
        assert len(groups) == 2
        resolved_group = next(group for group in groups if group["contributor"] == contributor)
        unresolved_group = next(group for group in groups if group["contributor"] is None)
        assert resolved_group["rows"][0]["duplicate_reference"] is not None
        assert unresolved_group["speaker_label"] == "Speaker 2"

    def test_create_helper_surfaces_model_validation_errors(self, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="helper-validation-alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [podlove_segment("Alice", "1", "12")]},
        )
        candidate = get_voice_reference_candidate(transcript, speaker_label="Alice", candidate_rank=1)
        assert candidate is not None

        with pytest.raises(ValidationError) as exc_info:
            create_voice_reference_from_candidate(
                transcript,
                get_speaker_mapping_context(transcript),
                candidate,
                status=ContributorVoiceReference.Status.APPROVED,
                consent_confirmed=False,
            )

        assert "requires confirmed consent" in validation_error_message(exc_info.value)

    def test_voice_reference_create_form_accepts_pending_or_consented_approved(self):
        pending_form = VoiceReferenceCandidateCreateForm(
            {
                "action": "create-voice-reference",
                "speaker_label": "Alice",
                "candidate_rank": "1",
                "voice_reference_status": "pending",
            }
        )
        approved_form = VoiceReferenceCandidateCreateForm(
            {
                "action": "create-voice-reference",
                "speaker_label": "Alice",
                "candidate_rank": "1",
                "voice_reference_status": "approved",
                "consent_confirmed": "on",
            }
        )

        assert pending_form.is_valid()
        assert approved_form.is_valid()
