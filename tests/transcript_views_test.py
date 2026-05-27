import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.test import override_settings
from django.template import TemplateDoesNotExist
from django.urls import reverse
from django.utils import translation

from cast.devdata import create_transcript
from cast.forms import DRAFT_SPEAKER_ASSIGNMENT_PREFIX, SpeakerContributorMappingForm
from cast.models import Contributor, EpisodeContributor, Transcript
from cast.views.transcript import (
    _resolve_transcript_template,
    get_speaker_mapping_context,
    get_transcript_audio_sources,
)

from .factories import BlogFactory, EpisodeFactory
from .multisite_helpers import create_site_root


def get_endpoint_urls_without_args():
    urls = {}
    view_names = ["index", "add", "chooser", "chooser_upload"]
    for view_name in view_names:
        urls[view_name] = reverse(f"cast-transcript:{view_name}")
    return urls


def get_endpoint_urls_with_args(transcript):
    urls = {}
    view_names = ["edit", "delete", "chosen"]
    for view_name in view_names:
        urls[view_name] = reverse(f"cast-transcript:{view_name}", args=(transcript.id,))
    return urls


class TranscriptUrls:
    def __init__(self, transcript):
        self.transcript = transcript
        self.urls = get_endpoint_urls_without_args()
        self.urls.update(get_endpoint_urls_with_args(transcript))

    def __getattr__(self, item):
        return self.urls[item]


@pytest.fixture
def transcript_urls(transcript):
    return TranscriptUrls(transcript)


class TestAllTranscriptEndpoints:
    pytestmark = pytest.mark.django_db

    def test_get_all_not_authenticated(self, client, transcript_urls):
        for view_name, url in transcript_urls.urls.items():
            r = client.get(url)

            # redirect to log in
            assert r.status_code == 302
            login_url = reverse("wagtailadmin_login")
            assert login_url in r.url

    def test_get_all_authenticated(self, admin_client, transcript_urls):
        for view_name, url in transcript_urls.urls.items():
            r = admin_client.get(url)

            # assert we are not redirected to log in
            assert r.status_code == 200


class TestTranscriptIndex:
    pytestmark = pytest.mark.django_db

    def test_get_index(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.index)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        assert transcript_urls.transcript.audio.title in content

    def test_get_index_ajax(self, admin_client, transcript_urls):
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
        r = admin_client.get(transcript_urls.index, **headers)

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "table" in content
        assert "listing" in content

        # make sure transcript_urls.transcript is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_search(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.index, {"q": transcript_urls.transcript.audio.title})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure transcript_urls.transcript.audio is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_search_invalid(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.index, {"q": " "})

        assert r.status_code == 200
        content = r.content.decode("utf-8")

        # make sure it's the media results page
        assert "html" in content
        assert "media-results" in content

        # make sure transcript_urls.transcript.audio is included in results
        assert transcript_urls.transcript.audio.title in content

    def test_get_index_with_pagination(self, admin_client, user, audio):
        transcript = Transcript(audio=audio)
        transcript.save()
        index_url = reverse("cast-transcript:index")
        with patch("cast.views.transcript.MENU_ITEM_PAGINATION", return_value=1):
            r = admin_client.get(index_url, {"p": "1"})
        transcripts = r.context["transcripts"]

        # make sure we got last transcript from first page
        assert len(transcripts) == 1
        assert transcripts[0] == transcripts[-1]

        with patch("cast.views.transcript.MENU_ITEM_PAGINATION", return_value=1):
            r = admin_client.get(index_url, {"p": "2"})
        transcripts = r.context["transcripts"]

        # make sure we got first transcript from last page
        assert len(transcripts) == 1
        assert transcripts[0] == transcripts[0]


class TestTranscriptAdd:
    pytestmark = pytest.mark.django_db

    def test_get_add_transcript(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.add)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Uploading…" in content

    def test_post_add_transcript_invalid_form(self, admin_client, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        add_url = reverse("cast-transcript:add")

        post_data = {
            "podlove": podlove_transcript,
            "tags": "foo,bar,baz",  # invalid
        }
        r = admin_client.post(add_url, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200
        assert r.context["message"] == "The transcript file could not be saved due to errors."

        # make sure we didn't create an transcript
        assert Transcript.objects.first() is None

    def test_post_add_transcript(self, admin_client, audio, podlove_transcript):
        add_url = reverse("cast-transcript:add")

        post_data = {
            "podlove": podlove_transcript,
            "audio": audio.id,
        }
        r = admin_client.post(add_url, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == reverse("cast-transcript:index")

        # make sure field were saved correctly
        transcript = Transcript.objects.first()
        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content


class TestTranscriptSpeakerMapping:
    pytestmark = pytest.mark.django_db

    def test_get_speaker_labels_from_podlove_and_dote(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 2", "voice": "Speaker 1", "text": "Hello"},
                    {"speaker": "", "voice": None, "text": "empty"},
                    "not an object",
                ]
            },
            dote={
                "lines": [
                    {"speakerDesignation": "Speaker 3", "text": "Hi"},
                    {"speakerDesignation": "  ", "text": "blank"},
                    "not an object",
                ]
            },
        )

        assert transcript.get_speaker_labels() == ["Speaker 1", "Speaker 2", "Speaker 3"]

    def test_get_speaker_labels_handles_missing_and_invalid_files(self, audio):
        transcript = create_transcript(audio=audio)
        assert transcript.get_speaker_labels() == []

        transcript.podlove.name = "cast_transcript/missing-podlove.json"
        transcript.dote.save("invalid-dote.json", ContentFile("not json"))
        transcript.save()
        assert transcript.get_speaker_labels() == []

        transcript.podlove.save("list-podlove.json", ContentFile("[]"))
        transcript.dote.name = "cast_transcript/missing-dote.json"
        transcript.save()
        assert transcript.get_speaker_labels() == []

    def test_speaker_labels_samples_and_rewrite_strip_label_whitespace(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {
                        "speaker": " Speaker 1 ",
                        "voice": " Speaker 1 ",
                        "start": "00:00:01.500",
                        "text": "This sample sentence has enough content to identify speaker one.",
                    }
                ]
            },
            dote={
                "lines": [
                    {
                        "speakerDesignation": " Speaker 2 ",
                        "startTime": "00:00:02,500",
                        "text": "This sample sentence has enough content to identify speaker two.",
                    }
                ]
            },
        )

        assert transcript.get_speaker_labels() == ["Speaker 1", "Speaker 2"]
        samples = transcript.get_speaker_samples()
        assert sorted(samples.keys()) == ["Speaker 1", "Speaker 2"]

        assert transcript.rewrite_speaker_labels({"Speaker 1": "Alice", "Speaker 2": "Bob"})

        with transcript.podlove.open("r") as podlove_file:
            podlove_data = json.load(podlove_file)
        with transcript.dote.open("r") as dote_file:
            dote_data = json.load(dote_file)
        assert podlove_data["transcripts"][0]["speaker"] == "Alice"
        assert podlove_data["transcripts"][0]["voice"] == "Alice"
        assert dote_data["lines"][0]["speakerDesignation"] == "Bob"

    def test_get_speaker_samples_spreads_useful_podlove_samples(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    "not an object",
                    {"speaker": "", "text": "No speaker label here"},
                    {"speaker": "Speaker 1", "text": None},
                    {"speaker": "Speaker 1", "start_ms": 620, "text": "ja"},
                    {
                        "speaker": "Speaker 1",
                        "start_ms": 10_000,
                        "text": "First substantial sentence from speaker one that is long enough to be useful.",
                    },
                    {
                        "speaker": "Speaker 1",
                        "start": "00:05:00.000",
                        "text": "Second substantial sentence from speaker one that helps identify the voice.",
                    },
                    {
                        "speaker": "Speaker 1",
                        "startTime": 900,
                        "text": "Third substantial sentence from speaker one with useful identifying content.",
                    },
                    {
                        "speaker": "Speaker 1",
                        "start": "00:20:00.000",
                        "text": "Fourth substantial sentence from speaker one near the end of the episode.",
                    },
                    {
                        "voice": "Voice 1",
                        "text": "Voice only segment has enough words to become a transcript sample.",
                    },
                ]
            },
        )

        samples = transcript.get_speaker_samples(max_chars=48)

        assert [sample.timestamp_label for sample in samples["Speaker 1"]] == ["00:10", "15:00", "20:00"]
        assert samples["Speaker 1"][0].text == "First substantial sentence from speaker one..."
        assert samples["Speaker 1"][0].start_seconds == 10
        assert samples["Speaker 1"][0].has_start_time
        assert [sample.text for sample in samples["Speaker 1"]] == [
            "First substantial sentence from speaker one...",
            "Third substantial sentence from speaker one...",
            "Fourth substantial sentence from speaker one...",
        ]
        assert samples["Voice 1"][0].timestamp_label == ""
        assert samples["Voice 1"][0].start_seconds is None
        assert not samples["Voice 1"][0].has_start_time
        assert transcript.get_speaker_samples(limit=1)["Speaker 1"][0].timestamp_label == "00:10"
        assert transcript.get_speaker_samples(limit=0) == {}

    def test_get_speaker_samples_uses_dote_fallback_and_low_signal_fallback(self, audio):
        low_signal_text = "ja ja ja ja ja ja ja ja ja ja ja ja ja ja ja ja"
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 2", "start": "00:00:00.000", "text": low_signal_text},
                    {"speaker": "Speaker 3", "start": "00:00:02.000", "text": low_signal_text},
                ]
            },
            dote={
                "lines": [
                    "not an object",
                    {"speakerDesignation": "", "text": "Missing speaker"},
                    {"speakerDesignation": "Speaker 4", "text": None},
                    {
                        "speakerDesignation": "Speaker 2",
                        "startTime": "00:00:01,500",
                        "text": "DOTe fallback has a longer sentence with enough identifying words.",
                    },
                    {
                        "speakerDesignation": "Hour Speaker",
                        "startTime": "01:02:03,900",
                        "text": "Hour timestamp sentence has enough useful identifying transcript content.",
                    },
                ]
            },
        )

        samples = transcript.get_speaker_samples()

        assert samples["Speaker 2"][0].text == "DOTe fallback has a longer sentence with enough identifying words."
        assert samples["Speaker 2"][0].timestamp_label == "00:01"
        assert samples["Speaker 2"][0].start_seconds == 1.5
        assert samples["Speaker 3"][0].text == low_signal_text
        assert samples["Hour Speaker"][0].timestamp_label == "01:02:03"

    def test_speaker_sample_helpers_handle_edge_cases(self):
        assert Transcript._parse_timestamp_seconds(True) is None
        assert Transcript._parse_timestamp_seconds(None) is None
        assert Transcript._parse_timestamp_seconds("") is None
        assert Transcript._parse_timestamp_seconds("not a timestamp") is None
        assert Transcript._parse_timestamp_seconds("00:00:not-a-number") is None
        assert Transcript._parse_timestamp_seconds("00:00:00:00") is None
        assert Transcript._parse_timestamp_seconds(-1) is None
        assert Transcript._parse_timestamp_seconds("-1") is None
        assert Transcript._parse_timestamp_seconds("65.5") == 65.5
        assert Transcript._parse_timestamp_seconds("01:02") == 62
        assert (
            Transcript._parse_record_start_seconds(
                {"start_ms": False, "start": "00:00:02"},
                timestamp_fields=("start",),
            )
            == 2
        )
        assert Transcript._parse_record_start_seconds({"start_ms": -1}, timestamp_fields=("start",)) is None
        assert Transcript._format_sample_timestamp(None) == ""

        assert Transcript._clean_sample_text(5) == ""
        assert not Transcript._sample_text_is_useful("short", min_chars=10, min_words=1)
        assert not Transcript._sample_text_is_useful("one two three", min_chars=1, min_words=4)
        assert not Transcript._sample_text_is_useful("okay", min_chars=1, min_words=1)
        assert not Transcript._sample_text_is_useful("mhm mhm mhm mhm", min_chars=1, min_words=4)
        assert Transcript._sample_text_is_useful("你好 你好 你好 你好", min_chars=1, min_words=4)

    def test_rewrite_speaker_labels_updates_podlove_and_dote_but_not_vtt(self, audio):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nSpeaker 1: unchanged"
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"},
                    {"speaker": "Speaker 2", "voice": "Other", "text": "Hi"},
                    "not an object",
                ]
            },
            dote={
                "lines": [
                    {"speakerDesignation": "Speaker 2", "text": "Hi"},
                    {"speakerDesignation": None, "text": "No speaker"},
                    "not an object",
                ]
            },
            vtt=vtt,
        )

        assert transcript.rewrite_speaker_labels({"Speaker 1": "Alice", "Speaker 2": "Bob"})

        with transcript.podlove.open("r") as podlove_file:
            podlove_data = json.load(podlove_file)
        with transcript.dote.open("r") as dote_file:
            dote_data = json.load(dote_file)
        with transcript.vtt.open("r") as vtt_file:
            vtt_content = vtt_file.read()
        assert podlove_data["transcripts"][0]["speaker"] == "Alice"
        assert podlove_data["transcripts"][0]["voice"] == "Alice"
        assert podlove_data["transcripts"][1]["speaker"] == "Bob"
        assert podlove_data["transcripts"][1]["voice"] == "Other"
        assert dote_data["lines"][0]["speakerDesignation"] == "Bob"
        assert vtt_content == vtt

    def test_rewrite_speaker_labels_returns_false_without_changes(self, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )

        assert not transcript.rewrite_speaker_labels({})
        assert not transcript.rewrite_speaker_labels({"Speaker 1": "Speaker 1"})
        assert not transcript.rewrite_speaker_labels({"Speaker 2": "Alice"})

    def test_save_json_file_handles_missing_existing_file(self, audio):
        transcript = create_transcript(audio=audio, podlove={"transcripts": []})
        transcript.podlove.storage.delete(transcript.podlove.name)

        transcript._save_json_file("podlove", {"transcripts": [{"speaker": "Speaker 1"}]})

        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"] == [{"speaker": "Speaker 1"}]

    def test_speaker_mapping_form_maps_to_episode_contributor_display_name(self, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        form = SpeakerContributorMappingForm(
            {"action": "map-speakers", "speaker_0": str(assignment.pk)},
            speaker_labels=["Speaker 1"],
            contributor_assignments=[assignment],
        )

        assert form.is_valid()
        assert form.speaker_mapping == {"Speaker 1": "Alice"}
        assert form.fields["speaker_0"].choices == [("", "Leave unchanged"), (str(assignment.pk), "Alice (Host)")]

    def test_speaker_mapping_form_labels_multiple_episodes(self, episode, podcast_episode_with_same_audio):
        alice = Contributor.objects.create(display_name="Alice", slug="alice")
        bob = Contributor.objects.create(display_name="Bob", slug="bob")
        first_assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=alice,
            role=EpisodeContributor.ROLE_HOST,
        )
        second_assignment = EpisodeContributor.objects.create(
            episode=podcast_episode_with_same_audio,
            contributor=bob,
            role=EpisodeContributor.ROLE_GUEST,
        )
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )

        context = get_speaker_mapping_context(transcript)
        form = SpeakerContributorMappingForm(**context)

        assert context["multiple_episodes"] is True
        assert context["contributor_assignments"] == [first_assignment, second_assignment]
        assert form.fields["speaker_0"].choices == [
            ("", "Leave unchanged"),
            (str(first_assignment.pk), f"Alice (Host) — {episode.title}"),
            (str(second_assignment.pk), f"Bob (Guest) — {podcast_episode_with_same_audio.title}"),
        ]

    def test_speaker_mapping_context_uses_draft_contributor_assignments(self, episode):
        contributor = Contributor.objects.create(display_name="Draft Host", slug="draft-host")
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=contributor,
                role=EpisodeContributor.ROLE_HOST,
            )
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )

        context = get_speaker_mapping_context(transcript)
        form = SpeakerContributorMappingForm(**context)

        assert EpisodeContributor.objects.filter(episode=episode).count() == 0
        assert [assignment.display_name for assignment in context["contributor_assignments"]] == ["Draft Host"]
        assert context["contributor_assignments"][0].pk is None
        draft_value = f"{DRAFT_SPEAKER_ASSIGNMENT_PREFIX}{episode.pk}:{contributor.pk}:{EpisodeContributor.ROLE_HOST}"
        assert form.fields["speaker_0"].choices == [("", "Leave unchanged"), (draft_value, "Draft Host (Host)")]

    def test_speaker_mapping_context_uses_stable_draft_assignment_values_with_mixed_assignments(self, episode):
        saved_contributor = Contributor.objects.create(display_name="Saved Host", slug="saved-host")
        saved_assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=saved_contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        hidden_contributor = Contributor.objects.create(
            display_name="Hidden Guest", slug="hidden-guest", visible=False
        )
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=draft_contributor,
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=1,
            )
        )
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=hidden_contributor,
                role=EpisodeContributor.ROLE_GUEST,
                sort_order=2,
            )
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )

        form = SpeakerContributorMappingForm(**get_speaker_mapping_context(transcript))

        draft_value = (
            f"{DRAFT_SPEAKER_ASSIGNMENT_PREFIX}{episode.pk}:{draft_contributor.pk}:{EpisodeContributor.ROLE_GUEST}"
        )
        assert form.fields["speaker_0"].choices == [
            ("", "Leave unchanged"),
            (str(saved_assignment.pk), "Saved Host (Host)"),
            (draft_value, "Draft Guest (Guest)"),
        ]

    def test_post_speaker_mapping_uses_draft_contributor_assignments(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Draft Host", slug="draft-host")
        episode.contributor_assignments.add(
            EpisodeContributor(
                contributor=contributor,
                role=EpisodeContributor.ROLE_HOST,
            )
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        draft_value = f"{DRAFT_SPEAKER_ASSIGNMENT_PREFIX}{episode.pk}:{contributor.pk}:{EpisodeContributor.ROLE_HOST}"

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": draft_value})

        assert response.status_code == 302
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Draft Host"

    def test_post_speaker_mapping_rewrites_transcript_files(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        assignment = EpisodeContributor.objects.create(
            episode=episode,
            contributor=contributor,
            role=EpisodeContributor.ROLE_HOST,
        )
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
            dote={"lines": [{"speakerDesignation": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": str(assignment.pk)})

        assert response.status_code == 302
        assert response.url == edit_url
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Alice"
        with transcript.dote.open("r") as dote_file:
            assert json.load(dote_file)["lines"][0]["speakerDesignation"] == "Alice"

    def test_post_speaker_mapping_with_no_selected_contributor_keeps_labels(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": ""})

        assert response.status_code == 302
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Speaker 1"

    def test_post_speaker_mapping_invalid_form(self, admin_client, episode):
        contributor = Contributor.objects.create(display_name="Alice", slug="alice")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": "99999"})

        assert response.status_code == 200
        assert response.context["message"] == "The speaker labels could not be updated due to errors."

    def test_post_speaker_mapping_without_contributors_rejects_bypassed_disabled_button(self, admin_client, episode):
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={"transcripts": [{"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Hello"}]},
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.post(edit_url, {"action": "map-speakers", "speaker_0": "99999"})

        assert response.status_code == 200
        assert response.context["message"] == "The speaker labels could not be updated due to errors."
        with transcript.podlove.open("r") as podlove_file:
            assert json.load(podlove_file)["transcripts"][0]["speaker"] == "Speaker 1"

    def test_get_edit_transcript_renders_speaker_samples_and_audio_seek_controls(self, admin_client, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {
                        "speaker": "Speaker 1",
                        "start": "00:00:01.500",
                        "text": "This sample sentence is long enough to identify the diarized speaker.",
                    }
                ]
            },
        )
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        with translation.override("de"):
            response = admin_client.get(edit_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "cast-speaker-mapping__row" in content
        assert "This sample sentence is long enough to identify the diarized speaker." in content
        assert "data-cast-speaker-audio" in content
        assert 'type="audio/mp4"' in content
        assert 'data-cast-speaker-seek="1.5"' in content

    def test_get_edit_transcript_omits_audio_seek_controls_when_audio_file_is_missing(self, admin_client, audio):
        transcript = create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {
                        "speaker": "Speaker 1",
                        "start": "00:00:01.500",
                        "text": "This sample sentence is long enough to render without playable audio.",
                    }
                ]
            },
        )
        audio.m4a.storage.delete(audio.m4a.name)
        edit_url = reverse("cast-transcript:edit", args=(transcript.pk,))

        response = admin_client.get(edit_url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "This sample sentence is long enough to render without playable audio." in content
        assert "<audio controls" not in content
        assert 'data-cast-speaker-seek="1.5"' not in content
        assert "00:01" in content

    def test_get_transcript_audio_sources_skips_unplayable_fields(self):
        class MissingUrlField:
            name = "cast_audio/no-url.mp3"

        class ExistingStorage:
            def exists(self, name):
                return True

        class BrokenUrlField:
            name = "cast_audio/broken.m4a"
            storage = ExistingStorage()

            @property
            def url(self):
                raise OSError

        audio = SimpleNamespace(
            uploaded_audio_files=[("mp3", MissingUrlField()), ("m4a", BrokenUrlField())],
            mime_lookup={"mp3": "audio/mpeg", "m4a": "audio/mp4"},
            title_lookup={"mp3": "Audio MP3", "m4a": "Audio M4A"},
            get_file_size=lambda _audio_format: 1,
        )
        transcript = SimpleNamespace(audio=audio)

        assert get_transcript_audio_sources(transcript) == []


class TestTranscriptEdit:
    pytestmark = pytest.mark.django_db

    def test_get_edit_transcript(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.edit)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_get_edit_transcript_detail(self, admin_client, transcript):
        edit_url = reverse("cast-transcript:edit", args=(transcript.id,))
        r = admin_client.get(edit_url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Delete" in content

    def test_post_edit_transcript_invalid_form(self, admin_client, transcript_urls, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        post_data = {"podlove": podlove_transcript}
        r = admin_client.post(transcript_urls.edit, post_data)

        # make sure we don't get redirected to index
        assert r.status_code == 200

    def test_post_edit_audio_podlove(self, admin_client, transcript_urls, podlove_transcript):
        audio = transcript_urls.transcript.audio
        post_data = {
            "podlove": podlove_transcript,
            "audio": audio.id,
        }
        r = admin_client.post(transcript_urls.edit, post_data)

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == transcript_urls.index

        # make sure transcript in podlove was changes
        transcript = transcript_urls.transcript
        transcript.refresh_from_db()

        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content


class TestTranscriptDelete:
    pytestmark = pytest.mark.django_db

    def test_get_delete_transcript(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.delete)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Are you sure you want to delete this transcript?" in content

    def test_post_delete_transcript(self, admin_client, transcript_urls):
        # post data is necessary because of if request.POST
        r = admin_client.post(transcript_urls.delete, {"delete": "yes"})

        # make sure we get redirected to index
        assert r.status_code == 302
        assert r.url == transcript_urls.index

        # make sure transcript was deleted
        transcript = transcript_urls.transcript
        with pytest.raises(Transcript.DoesNotExist):
            transcript.refresh_from_db()


class TestTranscriptChosen:
    pytestmark = pytest.mark.django_db

    def test_get_chosen_transcript_not_found(self, admin_client, transcript_urls):
        transcript_urls.transcript.delete()
        r = admin_client.get(transcript_urls.chosen)

        assert r.status_code == 404

    def test_get_chosen_transcript_success(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.chosen)

        assert r.status_code == 200

        # make sure returned data belongs to the right transcript instance
        data = r.json()
        assert data["result"]["id"] == transcript_urls.transcript.id


class TestTranscriptChooser:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_in_chooser(self, admin_client, transcript_urls):
        audio = transcript_urls.transcript.audio
        r = admin_client.get(transcript_urls.chooser)

        assert r.status_code == 200

        # make sure existing transcript is in chooser
        content = r.content.decode("utf-8")
        assert audio.title in content

        # make sure prefix for form fields is set
        assert "media-chooser-upload" in content

    def test_get_chooser_with_search(self, admin_client, transcript_urls):
        r = admin_client.get(transcript_urls.chooser, {"q": transcript_urls.transcript.audio.title})

        assert r.status_code == 200

        # make sure searched transcript is included in results
        assert r.context["transcripts"][0] == transcript_urls.transcript

    def test_get_chooser_with_search_invalid(self, admin_client, transcript_urls):
        # {"p": "1"} (page 1) leads to the search form being invalid
        r = admin_client.get(transcript_urls.chooser, {"p": "1"})

        assert r.status_code == 200

        # make sure searched transcripts is included in results
        assert r.context["transcripts"][0] == transcript_urls.transcript


class TestTranscriptChooserUpload:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_in_chooser_upload(self, admin_client, transcript_urls):
        audio = transcript_urls.transcript.audio
        r = admin_client.get(transcript_urls.chooser_upload)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert audio.title in content

    def test_post_upload_transcript_form_invalid(self, admin_client, podlove_transcript):
        podlove_transcript.seek(podlove_transcript.size)  # seek to end to make file empty/invalid
        upload_url = reverse("cast-transcript:chooser_upload")
        post_data = {"media-chooser-podlove": podlove_transcript}
        r = admin_client.post(upload_url, post_data)

        assert r.status_code == 200
        assert r.context["message"] == "The transcript could not be saved due to errors."

    def test_post_upload_transcript(self, admin_client, podlove_transcript, settings, audio):
        settings.DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
        upload_url = reverse("cast-transcript:chooser_upload")
        prefix = "media-chooser-upload"
        post_data = {
            f"{prefix}-audio": audio.id,
            f"{prefix}-podlove": podlove_transcript,
        }
        r = admin_client.post(upload_url, post_data)

        assert r.status_code == 200

        # make sure field was saved correctly
        transcript = Transcript.objects.first()
        with transcript.podlove.open("r") as file:
            saved_transcript_content = file.read()
        podlove_transcript.seek(0)
        submitted_transcript_content = podlove_transcript.read().decode("utf-8")
        assert saved_transcript_content == submitted_transcript_content

        # teardown
        transcript.podlove.delete()


class TestGetTranscriptAsJson:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_json_not_found(self, client):
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_podlove(self, client):
        # Given a transcript without a podlove file
        transcript = create_transcript()

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "Podlove file not available"

    def test_get_transcript_as_json_not_valid_json(self, client):
        # Given a transcript that is not valid JSON
        transcript = create_transcript()
        transcript.podlove.save("podlove.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in podlove file"

    def test_get_transcript_as_json_success(self, client):
        # Given a transcript in podlove format
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "start_ms": 620,
                    "end": "00:00:05.160",
                    "end_ms": 5160,
                    "speaker": "",
                    "voice": "",
                    "text": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                }
            ]
        }
        transcript = create_transcript(podlove=podlove)

        # When we request the transcript as JSON
        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        assert r.json()["transcripts"] == podlove["transcripts"]

    def test_get_transcript_as_json_sanitizes_public_speaker_labels(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=live_contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        episode.contributor_assignments.add(
            EpisodeContributor(contributor=draft_contributor, role=EpisodeContributor.ROLE_GUEST, sort_order=1)
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Live Host", "voice": "Live Host", "text": "Live speaker"},
                    {"speaker": "Draft Guest", "voice": "Draft Guest", "text": "Draft speaker"},
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Unmapped speaker"},
                ]
            },
        )

        url = reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert data["transcripts"][0]["speaker"] == "Live Host"
        assert "speaker" not in data["transcripts"][1]
        assert "voice" not in data["transcripts"][1]
        assert "speaker" not in data["transcripts"][2]
        assert "voice" not in data["transcripts"][2]
        with transcript.podlove.open("r") as podlove_file:
            stored_data = json.load(podlove_file)
        assert stored_data["transcripts"][1]["speaker"] == "Draft Guest"

    def test_public_direct_endpoints_sanitize_draft_only_audio(self, client, episode):
        episode.live = False
        episode.save(update_fields=["live"])
        transcript = create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"speaker": "Draft Guest", "voice": "Draft Guest", "text": "Draft speaker"},
                    {"speaker": "Speaker 1", "voice": "Speaker 1", "text": "Unmapped speaker"},
                ]
            },
            dote={
                "lines": [
                    {
                        "startTime": "00:00:00,000",
                        "endTime": "00:00:01,000",
                        "speakerDesignation": "Draft Guest",
                        "text": "Draft speaker",
                    },
                    {
                        "startTime": "00:00:01,000",
                        "endTime": "00:00:02,000",
                        "speakerDesignation": "Speaker 1",
                        "text": "Unmapped speaker",
                    },
                ]
            },
            vtt=(
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:01.000\n"
                "Speaker 1: Unmapped speaker\n\n"
                "00:00:01.000 --> 00:00:02.000\n"
                "<v Draft Guest>Draft speaker</v>\n"
            ),
        )

        podlove_response = client.get(reverse("cast:podlove-transcript-json", kwargs={"pk": transcript.id}))
        podcastindex_response = client.get(reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id}))
        vtt_response = client.get(reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id}))
        html_response = client.get(reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id}))

        assert podlove_response.status_code == 200
        assert "speaker" not in podlove_response.json()["transcripts"][0]
        assert "voice" not in podlove_response.json()["transcripts"][0]
        assert "speaker" not in podlove_response.json()["transcripts"][1]
        assert "voice" not in podlove_response.json()["transcripts"][1]
        assert podcastindex_response.status_code == 200
        assert [segment["speaker"] for segment in podcastindex_response.json()["segments"]] == ["", ""]
        assert vtt_response.status_code == 200
        vtt_content = vtt_response.content.decode("utf-8")
        assert "Speaker 1" not in vtt_content
        assert "Draft Guest" not in vtt_content
        assert "Draft speaker" in vtt_content
        assert html_response.status_code == 200
        html_content = html_response.content.decode("utf-8")
        assert "Draft Guest" not in html_content
        assert "Speaker 1" not in html_content
        assert "Draft speaker" in html_content
        with transcript.podlove.open("r") as podlove_file:
            stored_data = json.load(podlove_file)
        assert stored_data["transcripts"][0]["speaker"] == "Draft Guest"


class TestGetTranscriptAsPodcastIndexJson:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_json_not_found(self, client):
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_dote(self, client):
        # Given a transcript without a dote file
        transcript = create_transcript()

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "podcastindex JSON file not available"

    def test_get_transcript_as_json_not_valid_json(self, client):
        # Given a transcript that is not valid JSON
        transcript = create_transcript()
        transcript.dote.save("dote.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in dote file"

    def test_get_transcript_as_json_success(self, client):
        # Given a transcript in podlove format
        dote = {
            "lines": [
                {
                    "startTime": "00:00:00,620",
                    "endTime": "00:00:05,160",
                    "speakerDesignation": "speaker",
                    "text": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                }
            ]
        }
        transcript = create_transcript(dote=dote)

        # When we request the transcript as JSON
        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        assert r.json() == {
            "version": "1.0",
            "segments": [
                {
                    "startTime": 0.62,
                    "endTime": 5.16,
                    "speaker": "",
                    "body": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
                },
            ],
        }

    def test_get_transcript_as_json_missing_dote_file_returns_empty_json(self, client):
        transcript = create_transcript(dote={"lines": []})
        transcript.dote.storage.delete(transcript.dote.name)

        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        assert response.json() == {}

    def test_get_transcript_as_json_sanitizes_public_speaker_labels(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode, contributor=live_contributor, role=EpisodeContributor.ROLE_HOST
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        episode.contributor_assignments.add(
            EpisodeContributor(contributor=draft_contributor, role=EpisodeContributor.ROLE_GUEST)
        )
        episode.save_revision()
        transcript = create_transcript(
            audio=episode.podcast_audio,
            dote={
                "lines": [
                    {
                        "startTime": "00:00:00,000",
                        "endTime": "00:00:01,000",
                        "speakerDesignation": "Live Host",
                        "text": "Live speaker",
                    },
                    {
                        "startTime": "00:00:01,000",
                        "endTime": "00:00:02,000",
                        "speakerDesignation": "Draft Guest",
                        "text": "Draft speaker",
                    },
                    {
                        "startTime": "00:00:02,000",
                        "endTime": "00:00:03,000",
                        "speakerDesignation": "Speaker 1",
                        "text": "Unmapped speaker",
                    },
                ]
            },
        )

        url = reverse("cast:podcastindex-transcript-json", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        data = response.json()
        assert [segment["speaker"] for segment in data["segments"]] == ["Live Host", "", ""]
        assert "Draft Guest" not in response.content.decode("utf-8")
        assert "Speaker 1" not in response.content.decode("utf-8")
        with transcript.dote.open("r") as dote_file:
            stored_data = json.load(dote_file)
        assert stored_data["lines"][1]["speakerDesignation"] == "Draft Guest"


class TestGetTranscriptAsWebVtt:
    pytestmark = pytest.mark.django_db

    def test_get_transcript_as_vtt_not_found(self, client):
        url = reverse("cast:webvtt-transcript", kwargs={"pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_json_no_vtt(self, client):
        # Given a transcript without a vtt file
        transcript = create_transcript()

        # When we request the transcript as JSON
        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id})
        r = client.get(url)

        # Then we get a 404 response with an error message
        assert r.status_code == 404
        assert r.content.decode("utf-8") == "WebVTT file not available"

    def test_get_transcript_as_vtt_success(self, client):
        # Given a transcript in vtt format
        vtt = "WEBVTT\n\n00:00:00.620 --> 00:00:05.160\nJa, hallo liebe Hörerinnen und Hörer."
        transcript = create_transcript(vtt=vtt)

        # When we request the transcript as JSON
        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert content == vtt

    def test_get_transcript_as_vtt_sanitizes_generated_speaker_labels(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode, contributor=live_contributor, role=EpisodeContributor.ROLE_HOST
        )
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:01.000\n"
            "Live Host: Hallo\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Speaker 1: Unmapped speaker\n\n"
            "00:00:02.000 --> 00:00:03.000\n"
            "<v Speaker 2>Voice span speaker</v>\n"
        )
        transcript = create_transcript(audio=episode.podcast_audio, vtt=vtt)

        url = reverse("cast:webvtt-transcript", kwargs={"pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Live Host: Hallo" in content
        assert "Speaker 1" not in content
        assert "Unmapped speaker" in content
        assert "Speaker 2" not in content
        assert "Voice span speaker" in content


@pytest.fixture
def transcript_with_podlove():
    podlove = {
        "transcripts": [
            {
                "start": "00:00:00.620",
                "start_ms": 620,
                "end": "00:00:05.160",
                "end_ms": 5160,
                "speaker": "",
                "voice": "",
                "text": "Ja, hallo liebe Hörerinnen und Hörer. Willkommen beim Python-Podcast der 5ten Episode.",
            }
        ]
    }
    return create_transcript(podlove=podlove)


class TestGetTranscriptAsHtml:
    pytestmark = pytest.mark.django_db

    def test_resolve_transcript_template_falls_back_for_missing_theme(self, mocker):
        mocker.patch("cast.views.transcript.get_template", side_effect=TemplateDoesNotExist("missing"))

        assert _resolve_transcript_template("theme-without-transcript") == "cast/plain/transcript.html"

    def test_get_transcript_as_html_not_found(self, client):
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": 1})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_html_no_podlove(self, client):
        transcript = create_transcript()
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.pk})
        r = client.get(url)
        assert r.status_code == 404

    def test_get_transcript_as_html_broken_json(self, client):
        # Given a transcript that is not valid JSON
        transcript = create_transcript()
        transcript.podlove.save("podlove.json", ContentFile("not valid json"))
        transcript.save()

        # When we request the transcript as JSON
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id})
        r = client.get(url)

        # Then we get a 400 response with an error message
        assert r.status_code == 400
        assert r.content.decode("utf-8") == "Invalid JSON format in podlove file"

    def test_get_transcript_as_html_success(self, client, transcript_with_podlove):
        # Given a transcript in podlove format
        transcript = transcript_with_podlove

        # When we request the transcript as HTML
        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert "hallo liebe Hörerinnen und Hörer" in content

    def test_get_transcript_as_html_falls_back_to_plain_template_for_missing_optional_theme_template(
        self, client, transcript_with_podlove, mocker
    ):
        transcript = transcript_with_podlove
        template_base_dir = "theme-without-transcript"

        mocker.patch("cast.views.transcript.get_template_base_dir", return_value=template_base_dir)

        def fake_get_template(name: str):
            if name == f"cast/{template_base_dir}/transcript.html":
                raise TemplateDoesNotExist(name)
            return object()

        mocker.patch("cast.views.transcript.get_template", side_effect=fake_get_template)

        url = reverse("cast:html-transcript-no-post", kwargs={"transcript_pk": transcript.id})
        response = client.get(url)

        assert response.status_code == 200
        assert "cast/plain/transcript.html" in [template.name for template in response.templates]

    def test_get_transcript_as_html_success_from_post(self, client, transcript_with_podlove, post):
        # Given a transcript in podlove format
        transcript = transcript_with_podlove

        # When we request the transcript as HTML
        url = reverse("cast:html-transcript", kwargs={"transcript_pk": transcript.id, "post_pk": post.id})
        r = client.get(url)
        assert r.status_code == 200

        # Then we get the transcript in the expected format
        content = r.content.decode("utf-8")
        assert "hallo liebe Hörerinnen und Hörer" in content

    def test_get_transcript_as_html_redirects_for_episode(self, client, episode):
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "end": "00:00:05.160",
                    "speaker": "Host",
                    "text": "Hallo und willkommen.",
                }
            ]
        }
        transcript = create_transcript(audio=episode.podcast_audio, podlove=podlove)
        url = reverse("cast:html-transcript", kwargs={"transcript_pk": transcript.id, "post_pk": episode.id})

        r = client.get(url)

        assert r.status_code == 302
        assert r.url == reverse(
            "cast:episode-transcript",
            kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug},
        )

    def test_get_transcript_as_html_canonical_success(self, client, episode):
        contributor = Contributor.objects.create(display_name="Host", slug="host")
        EpisodeContributor.objects.create(episode=episode, contributor=contributor, role=EpisodeContributor.ROLE_HOST)
        podlove = {
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "end": "00:00:05.160",
                    "speaker": "Host",
                    "text": "Hallo und willkommen.",
                }
            ]
        }
        create_transcript(audio=episode.podcast_audio, podlove=podlove)
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 200
        content = r.content.decode("utf-8")
        assert "Hallo und willkommen." in content
        assert "Host" in content
        assert episode.title in content
        assert episode.get_url() in content

    def test_get_transcript_as_html_canonical_sanitizes_public_speaker_labels(self, client, episode):
        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode, contributor=live_contributor, role=EpisodeContributor.ROLE_HOST
        )
        draft_contributor = Contributor.objects.create(display_name="Draft Guest", slug="draft-guest")
        episode.contributor_assignments.add(
            EpisodeContributor(contributor=draft_contributor, role=EpisodeContributor.ROLE_GUEST)
        )
        episode.save_revision()
        create_transcript(
            audio=episode.podcast_audio,
            podlove={
                "transcripts": [
                    {"start": "00:00:00.000", "speaker": "Live Host", "text": "Live speaker"},
                    {"start": "00:00:01.000", "speaker": "Draft Guest", "text": "Draft speaker"},
                    {"start": "00:00:02.000", "speaker": "Speaker 1", "text": "Unmapped speaker"},
                ]
            },
        )
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Live Host" in content
        assert "Live speaker" in content
        assert "Draft Guest" not in content
        assert "Draft speaker" in content
        assert "Speaker 1" not in content
        assert "Unmapped speaker" in content

    def test_get_transcript_as_html_canonical_without_transcript(self, client, episode):
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": episode.blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 404

    def test_get_transcript_as_html_canonical_mismatched_blog(self, client, episode, blog):
        url = reverse("cast:episode-transcript", kwargs={"blog_slug": blog.slug, "episode_slug": episode.slug})

        r = client.get(url)

        assert r.status_code == 404


@pytest.mark.django_db
def test_episode_transcript_uses_current_site_for_duplicate_blog_slug(client, user, audio):
    site1, site1_root = create_site_root(
        owner=user, hostname="transcript-site1.local", slug="transcript-site1-root", title="Transcript Site 1"
    )
    _site2, site2_root = create_site_root(
        owner=user, hostname="transcript-site2.local", slug="transcript-site2-root", title="Transcript Site 2"
    )
    blog1 = BlogFactory(owner=user, title="Blog 1", slug="shared-transcript-blog", parent=site1_root)
    blog2 = BlogFactory(owner=user, title="Blog 2", slug="shared-transcript-blog", parent=site2_root)
    episode1 = EpisodeFactory(
        owner=user, title="Episode 1", slug="shared-transcript-episode", parent=blog1, podcast_audio=audio
    )
    EpisodeFactory(owner=user, title="Episode 2", slug="shared-transcript-episode", parent=blog2, podcast_audio=audio)
    create_transcript(
        audio=audio,
        podlove={
            "transcripts": [
                {
                    "start": "00:00:00.620",
                    "end": "00:00:05.160",
                    "speaker": "Host",
                    "text": "Hello multisite transcript.",
                }
            ]
        },
    )

    url = reverse(
        "cast:episode-transcript",
        kwargs={"blog_slug": blog1.slug, "episode_slug": episode1.slug},
    )
    with override_settings(ALLOWED_HOSTS=["testserver", site1.hostname, "transcript-site2.local"]):
        response = client.get(url, HTTP_HOST=site1.hostname)

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Episode 1" in content
    assert "Episode 2" not in content
