"""Tests for naming a guest without a voice reference from the leftover diarization label."""

import json

import pytest
from django.core.files.base import ContentFile

from cast.models import Contributor, EpisodeContributor, Transcript
from cast.transcripts import known_speakers
from cast.transcripts.known_speakers import (
    KNOWN_SPEAKER_DECISION_REJECT,
    KNOWN_SPEAKER_EDITOR_DECISION_FIELD,
    MIXED_SPEAKERS_REASON,
)
from cast.transcripts.services import resolve_unreferenced_contributor_name, resolve_unreferenced_label_names
from tests.factories import EpisodeFactory


def segment(start, *, label, speaker=None, accept_reason=None, mixed=False):
    data = {
        "start": float(start),
        "speaker": speaker,
        "speaker_uncertain": speaker is None,
        "raw_diarization_speaker": label,
    }
    if accept_reason:
        data["speaker_accept_reason"] = accept_reason
    if mixed:
        data["speaker_uncertain_reason"] = MIXED_SPEAKERS_REASON
    return data


def host_votes(start, label, speaker, count=5):
    return [segment(start + offset, label=label, speaker=speaker) for offset in range(count)]


# Two referenced hosts with five confident segments each, then three guest
# segments on the leftover label "Speaker 3".
SEGMENTS = (
    host_votes(0, "Speaker 1", "Will")
    + host_votes(10, "Speaker 2", "Carlton")
    + [segment(20 + offset, label="Speaker 3") for offset in range(3)]
)
LABELS = {
    "Speaker 1": {"speaker": "Will", "seconds": 5.0},
    "Speaker 2": {"speaker": "Carlton", "seconds": 5.0},
    "Speaker 3": {"speaker": None, "seconds": 3.0},
}


def sidecar(*, segments=SEGMENTS, labels=LABELS, sent=("Will", "Carlton")):
    summary = {"strategy": "pyannote_known_speaker"}
    if sent is not None:
        summary["known_speakers"] = list(sent)
    if labels is not None:
        summary["raw_diarization_labels"] = labels
    return {"summary": summary, "segments": segments}


def podlove_for(segments):
    return {
        "version": 1,
        "transcripts": [
            {"start_ms": int(item["start"] * 1000), "speaker": "", "voice": "", "text": "x"} for item in segments
        ],
    }


def make_transcript(audio, speakers):
    transcript = Transcript.objects.create(audio=audio)
    transcript.podlove.save(
        "t.podlove.json", ContentFile(json.dumps(podlove_for(speakers["segments"])).encode()), save=False
    )
    transcript.speakers.save("t.speakers.json", ContentFile(json.dumps(speakers).encode()), save=False)
    transcript.save()
    return transcript


def assign(episode, display_name, *, role=EpisodeContributor.ROLE_HOST, visible=True):
    contributor = Contributor.objects.create(display_name=display_name, slug=display_name.lower(), visible=visible)
    EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=role)
    return contributor


@pytest.fixture()
def guest_episode(episode):
    assign(episode, "Will")
    assign(episode, "Carlton")
    assign(episode, "Eric", role=EpisodeContributor.ROLE_GUEST)
    return episode


def public_speakers(transcript):
    return [item["speaker"] for item in transcript.podlove_data["transcripts"]]


# Pure helpers


def test_raw_label_speakers_reads_the_summary_labels():
    summary = {"raw_diarization_labels": {**LABELS, "Speaker 4": "bad", 5: {"speaker": "x"}}}

    assert known_speakers.raw_label_speakers(summary, []) == {
        "Speaker 1": "Will",
        "Speaker 2": "Carlton",
        "Speaker 3": None,
    }


def test_raw_label_speakers_votes_when_the_summary_has_no_labels():
    segments = (
        host_votes(0, "Speaker 1", "Will")
        # Four votes are too few to tie a label to a speaker.
        + host_votes(10, "Speaker 2", "Carlton", count=4)
        # A split vote stays unmatched.
        + host_votes(20, "Speaker 3", "Will", count=3)
        + host_votes(30, "Speaker 3", "Carlton", count=3)
        # Speaker-track and uncertain segments do not vote.
        + [segment(40, label="Speaker 4", speaker="Will", accept_reason="speaker_track")]
        + [segment(41, label="Speaker 4")]
        # Segments without a raw label are ignored.
        + [segment(42, label=None, speaker="Will")]
    )

    assert known_speakers.raw_label_speakers({}, segments) == {
        "Speaker 1": "Will",
        "Speaker 2": None,
        "Speaker 3": None,
        "Speaker 4": None,
    }


@pytest.mark.parametrize(
    "label_speakers, expected",
    [
        ({"Speaker 1": "Will", "Speaker 2": None}, "Speaker 2"),
        ({"Speaker 1": "Will"}, None),
        ({"Speaker 1": None, "Speaker 2": None}, None),
    ],
)
def test_find_unmatched_label(label_speakers, expected):
    assert known_speakers.find_unmatched_label(label_speakers) == expected


def test_resolve_display_names_names_uncertain_segments_by_label():
    segments = [
        segment(0, label="Speaker 1", speaker="Will"),
        segment(1, label="Speaker 3"),
        segment(2, label="Speaker 3", mixed=True),
        segment(3, label="Speaker 1"),
        segment(4, label=None),
        {
            **segment(5, label="Speaker 3"),
            KNOWN_SPEAKER_EDITOR_DECISION_FIELD: {"action": KNOWN_SPEAKER_DECISION_REJECT},
        },
    ]

    names = known_speakers.resolve_display_names(segments, smooth=False, label_names={"Speaker 3": "Eric"})

    assert names == ["Will", "Eric", None, None, None, None]


def test_resolve_display_names_smooths_after_naming_labels():
    segments = [
        segment(0, label="Speaker 3"),
        segment(1, label="Speaker 1"),
        segment(2, label="Speaker 1", speaker="Will"),
    ]

    names = known_speakers.resolve_display_names(segments, smooth=True, label_names={"Speaker 3": "Eric"})

    assert names == ["Eric", "Eric", "Will"]


def test_resolve_display_names_leaves_mixed_guest_segments_to_smoothing():
    segments = [
        segment(0, label="Speaker 3"),
        segment(1, label="Speaker 3", mixed=True),
        segment(2, label="Speaker 1", speaker="Will"),
    ]

    # The guest rule skips the mixed segment; smoothing then fills it like any other gap.
    names = known_speakers.resolve_display_names(segments, smooth=True, label_names={"Speaker 3": "Eric"})

    assert names == ["Eric", "Eric", "Will"]


# Applying to a transcript


@pytest.mark.django_db
def test_apply_names_the_guest_without_reference(guest_episode):
    transcript = make_transcript(guest_episode.podcast_audio, sidecar())

    transcript.apply_known_speaker_suggestions(smooth=False)

    assert public_speakers(transcript) == ["Will"] * 5 + ["Carlton"] * 5 + ["Eric"] * 3


@pytest.mark.django_db
def test_apply_names_the_guest_from_an_older_sidecar_without_label_summary(guest_episode):
    transcript = make_transcript(guest_episode.podcast_audio, sidecar(labels=None))

    transcript.apply_known_speaker_suggestions(smooth=False)

    assert public_speakers(transcript)[-3:] == ["Eric"] * 3


@pytest.mark.django_db
@pytest.mark.parametrize(
    "speakers",
    [
        # Two labels nobody is tied to: which one is the guest is ambiguous.
        sidecar(labels={**LABELS, "Speaker 4": {"speaker": None, "seconds": 1.0}}),
        # A referenced host has no label of their own, so the leftover label may be theirs.
        sidecar(labels={"Speaker 1": {"speaker": "Will", "seconds": 5.0}, "Speaker 3": {"speaker": None}}),
        # Without the list of referenced speakers the guest cannot be determined.
        sidecar(sent=None),
    ],
)
def test_apply_leaves_the_guest_blank_when_labels_are_ambiguous(guest_episode, speakers):
    transcript = make_transcript(guest_episode.podcast_audio, speakers)

    transcript.apply_known_speaker_suggestions(smooth=False)

    assert public_speakers(transcript)[-3:] == [""] * 3


@pytest.mark.django_db
def test_apply_leaves_guests_blank_when_two_contributors_lack_references(guest_episode):
    assign(guest_episode, "Mia", role=EpisodeContributor.ROLE_GUEST)
    transcript = make_transcript(guest_episode.podcast_audio, sidecar())

    transcript.apply_known_speaker_suggestions(smooth=False)

    assert public_speakers(transcript)[-3:] == [""] * 3


@pytest.mark.django_db
def test_unreferenced_contributor_must_be_visible(episode):
    assign(episode, "Will")
    assign(episode, "Carlton")
    assign(episode, "Eric", role=EpisodeContributor.ROLE_GUEST, visible=False)
    transcript = make_transcript(episode.podcast_audio, sidecar())

    assert resolve_unreferenced_contributor_name(transcript, {"Will", "Carlton"}) is None


@pytest.mark.django_db
def test_unreferenced_contributor_needs_exactly_one_episode(audio):
    transcript = make_transcript(audio, sidecar())

    assert resolve_unreferenced_contributor_name(transcript, {"Will", "Carlton"}) is None


@pytest.mark.django_db
def test_unreferenced_contributor_ignores_audio_shared_by_episodes(guest_episode, podcast, body):
    EpisodeFactory(
        owner=podcast.owner, parent=podcast, title="second", slug="second", podcast_audio=guest_episode.podcast_audio
    )
    transcript = make_transcript(guest_episode.podcast_audio, sidecar())

    assert resolve_unreferenced_label_names(transcript, transcript.get_speaker_suggestions()) == {}
