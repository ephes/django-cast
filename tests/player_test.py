"""Tests for the custom audio player payload builder, settings, checks, and fallback endpoint."""

import logging
from datetime import timedelta

import pytest
from django.test import RequestFactory
from django.urls import reverse

from cast import appsettings
from cast.checks import check_cast_audio_player_settings, check_cast_setting_types
from cast.devdata import create_transcript
from cast.models.audio import ChapterMark
from cast.player import (
    _clock_seconds,
    _finite_number,
    audio_player_context_flags,
    build_chapters,
    build_cues,
    build_player_payload,
    build_sources,
    parse_chapter_start_seconds,
)


@pytest.fixture()
def rf_request():
    return RequestFactory().get("/")


class TestParseChapterStartSeconds:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("00:01:01", 61),
            ("01:02:03", 3723),
            ("02:05", 125),
            ("00:00:05.789", 5),
            (10, 10),
            (10.9, 10),
        ],
    )
    def test_valid(self, value, expected):
        assert parse_chapter_start_seconds(value) == expected

    @pytest.mark.parametrize("value", ["", "nonsense", "::", None, "-5", -5])
    def test_invalid(self, value):
        assert parse_chapter_start_seconds(value) is None


class TestNumberHelpers:
    @pytest.mark.parametrize("value", [True, False, "", "   ", "abc", object(), None, float("nan"), float("inf")])
    def test_finite_number_rejects(self, value):
        assert _finite_number(value) is None

    @pytest.mark.parametrize("value", [5, 5.5, "5", "5.5"])
    def test_finite_number_accepts(self, value):
        assert _finite_number(value) == float(value)

    @pytest.mark.parametrize("value", [123, None, "nocolon", "1:2:3:4", "aa:bb"])
    def test_clock_seconds_rejects(self, value):
        assert _clock_seconds(value) is None


@pytest.mark.django_db
class TestBuildSources:
    def test_single_format_absolute_url(self, audio, rf_request):
        sources = build_sources(audio, rf_request)
        assert sources == [{"type": "audio/mp4", "src": rf_request.build_absolute_uri(audio.m4a.url)}]
        assert sources[0]["src"].startswith("http")

    def test_missing_formats_omitted(self, audio, rf_request):
        # only m4a is present on the audio fixture
        types = [source["type"] for source in build_sources(audio, rf_request)]
        assert types == ["audio/mp4"]

    def test_relative_url_without_request(self, audio):
        sources = build_sources(audio, None)
        assert sources[0]["src"] == audio.m4a.url
        assert not sources[0]["src"].startswith("http")


@pytest.mark.django_db
class TestBuildChapters:
    def test_parses_and_orders(self, audio):
        ChapterMark.objects.create(audio=audio, start="00:00:10.000", title="Intro")
        ChapterMark.objects.create(audio=audio, start="00:01:00.000", title="Middle")
        chapters = build_chapters(audio)
        assert chapters == [{"start": 10, "title": "Intro"}, {"start": 60, "title": "Middle"}]

    def test_skips_empty_title_and_logs(self, audio, caplog):
        ChapterMark.objects.create(audio=audio, start="00:00:10.000", title="Keep")
        ChapterMark.objects.create(audio=audio, start="00:00:20.000", title="   ")
        with caplog.at_level(logging.INFO):
            chapters = build_chapters(audio)
        assert chapters == [{"start": 10, "title": "Keep"}]
        assert any("skipped 1 chapter" in message for message in caplog.messages)


@pytest.mark.django_db
class TestBuildCues:
    def _make(self, audio, segments):
        create_transcript(audio=audio, podlove={"transcripts": segments})

    def test_start_from_ms_preferred(self, audio, episode):
        self._make(
            audio,
            [{"start": "00:00:99.000", "start_ms": 1500, "end_ms": 3000, "text": "hi"}],
        )
        cues = build_cues(audio, episode=episode, duration=None)
        assert cues == [{"start": 1.5, "end": 3.0, "speaker": "", "text": "hi"}]

    def test_start_from_clock_string_when_no_ms(self, audio, episode):
        self._make(audio, [{"start": "00:00:02.000", "end": "00:00:04.000", "text": "hi"}])
        cues = build_cues(audio, episode=episode, duration=None)
        assert cues[0]["start"] == 2.0
        assert cues[0]["end"] == 4.0

    def test_skips_missing_start_and_empty_text_and_logs(self, audio, episode, caplog):
        self._make(
            audio,
            [
                {"text": "no start"},
                {"start_ms": 1000, "text": "   "},
                {"start_ms": 2000, "end_ms": 3000, "text": "good"},
                "not-a-dict",
            ],
        )
        with caplog.at_level(logging.INFO):
            cues = build_cues(audio, episode=episode, duration=None)
        assert [cue["text"] for cue in cues] == ["good"]
        assert any("skipped 3 transcript cue" in message for message in caplog.messages)

    def test_sorted_by_start(self, audio, episode):
        self._make(
            audio,
            [
                {"start_ms": 3000, "end_ms": 4000, "text": "third"},
                {"start_ms": 1000, "end_ms": 2000, "text": "first"},
                {"start_ms": 2000, "end_ms": 3000, "text": "second"},
            ],
        )
        cues = build_cues(audio, episode=episode, duration=None)
        assert [cue["text"] for cue in cues] == ["first", "second", "third"]

    def test_end_synthesized_from_next_cue(self, audio, episode, caplog):
        self._make(
            audio,
            [
                {"start_ms": 1000, "text": "missing end"},
                {"start_ms": 5000, "end_ms": 6000, "text": "has end"},
            ],
        )
        with caplog.at_level(logging.INFO):
            cues = build_cues(audio, episode=episode, duration=None)
        assert cues[0]["end"] == 5.0  # next cue's start
        assert any("synthesized end for 1" in message for message in caplog.messages)

    def test_end_le_start_synthesized(self, audio, episode):
        self._make(
            audio,
            [
                {"start_ms": 1000, "end_ms": 500, "text": "bad end"},
                {"start_ms": 4000, "end_ms": 5000, "text": "next"},
            ],
        )
        cues = build_cues(audio, episode=episode, duration=None)
        assert cues[0]["end"] == 4.0

    def test_duplicate_same_start_end_still_greater(self, audio, episode):
        self._make(
            audio,
            [
                {"start_ms": 1000, "text": "dup a"},
                {"start_ms": 1000, "text": "dup b"},
                {"start_ms": 3000, "end_ms": 4000, "text": "later"},
            ],
        )
        cues = build_cues(audio, episode=episode, duration=None)
        # both duplicates borrow the next strictly-greater start (3.0), never each other
        assert cues[0]["start"] == 1.0 and cues[0]["end"] == 3.0
        assert cues[1]["start"] == 1.0 and cues[1]["end"] == 3.0
        for cue in cues:
            assert cue["end"] > cue["start"]

    def test_last_cue_uses_duration(self, audio, episode):
        self._make(audio, [{"start_ms": 1000, "text": "only"}])
        cues = build_cues(audio, episode=episode, duration=30)
        assert cues[0]["end"] == 30.0

    def test_last_cue_default_span_without_duration(self, audio, episode):
        self._make(audio, [{"start_ms": 1000, "text": "only"}])
        cues = build_cues(audio, episode=episode, duration=None)
        assert cues[0]["end"] == 1.0 + 5.0

    def test_last_cue_default_span_when_duration_not_greater(self, audio, episode):
        self._make(audio, [{"start_ms": 10000, "text": "only"}])
        cues = build_cues(audio, episode=episode, duration=5)  # duration < start
        assert cues[0]["end"] == 10.0 + 5.0

    def test_no_transcript_returns_empty(self, audio, episode):
        assert build_cues(audio, episode=episode, duration=None) == []

    def test_missing_transcript_file_returns_empty(self, audio, episode):
        import os

        transcript = create_transcript(
            audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]}
        )
        os.unlink(transcript.podlove.path)  # field still set, file gone -> OSError on open
        assert build_cues(audio, episode=episode, duration=None) == []

    def test_transcript_without_podlove_returns_empty(self, audio, episode):
        create_transcript(audio=audio, vtt="WEBVTT\n\n00:00.000 --> 00:01.000\nhi\n")
        assert build_cues(audio, episode=episode, duration=None) == []

    def test_non_dict_json_returns_empty(self, audio, episode):
        from django.core.files.base import ContentFile

        transcript = create_transcript(
            audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]}
        )
        transcript.podlove.save("podlove.json", ContentFile(b"[1, 2, 3]"))
        transcript.save()
        assert build_cues(audio, episode=episode, duration=None) == []


@pytest.mark.django_db
class TestSanitizationParity:
    def test_non_public_speakers_removed_and_no_raw_fields(self, audio, episode):
        from cast.models import Contributor, EpisodeContributor

        live_contributor = Contributor.objects.create(display_name="Live Host", slug="live-host")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=live_contributor,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        episode.save_revision().publish()
        create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"start_ms": 0, "end_ms": 1000, "speaker": "Live Host", "voice": "Live Host", "text": "live"},
                    {"start_ms": 1000, "end_ms": 2000, "speaker": "Draft Guest", "voice": "Draft Guest", "text": "x"},
                ]
            },
        )
        cues = build_cues(audio, episode=episode, duration=None)
        speakers = {cue["speaker"] for cue in cues}
        assert "Live Host" in speakers
        assert "Draft Guest" not in speakers
        # only normalized keys are ever emitted; raw podlove fields never leak
        for cue in cues:
            assert set(cue.keys()) == {"start", "end", "speaker", "text"}


@pytest.mark.django_db
class TestBuildPlayerPayload:
    def test_shape_and_conversions(self, audio, episode, rf_request):
        audio.duration = timedelta(seconds=123)
        audio.save()
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        payload = build_player_payload(audio, post=episode, request=rf_request)
        assert payload["audioId"] == audio.pk
        assert payload["title"] == "foobar audio"
        assert payload["subtitle"] == ""
        assert payload["duration"] == 123
        assert payload["poster"] == ""
        assert payload["sources"] == [{"type": "audio/mp4", "src": rf_request.build_absolute_uri(audio.m4a.url)}]
        assert payload["chapters"] == []
        # Inline path is lazy: it carries the endpoint URL, never the cues.
        expected_url = rf_request.build_absolute_uri(
            reverse("cast:api:audio_player_transcript", kwargs={"pk": audio.pk}) + f"?post_id={episode.pk}"
        )
        assert payload["transcript"] == {"url": expected_url}

    def test_duration_none_when_unset(self, audio, episode, rf_request):
        audio.duration = None  # in-memory; the builder reads the attribute directly
        payload = build_player_payload(audio, post=episode, request=rf_request)
        assert payload["duration"] is None

    def test_poster_present_with_cover(self, episode_with_podcast_with_cover_image, rf_request):
        episode = episode_with_podcast_with_cover_image
        payload = build_player_payload(episode.podcast_audio, post=episode, request=rf_request)
        assert payload["poster"].startswith("http")

    def test_inline_returns_none_without_transcript(self, audio, episode, rf_request):
        # No transcript file -> inline transcript is None (no button rendered).
        payload = build_player_payload(audio, post=episode, request=rf_request)
        assert payload["transcript"] is None

    def test_inline_path_does_not_build_cues(self, audio, episode, rf_request, monkeypatch):
        # The whole point of lazy loading: the detail-page render must not build
        # or sanitize the transcript. Cue building happens only on the endpoint.
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        import cast.player as player_mod

        calls: list[int] = []
        real_build_cues = player_mod.build_cues

        def spy(*args, **kwargs):
            calls.append(1)
            return real_build_cues(*args, **kwargs)

        monkeypatch.setattr(player_mod, "build_cues", spy)
        inline = build_player_payload(audio, post=episode, request=rf_request)  # inline_transcript=True
        assert calls == []  # not built on the inline path
        assert "url" in inline["transcript"]
        build_player_payload(audio, post=episode, request=rf_request, inline_transcript=False)
        assert calls == [1]  # built on the endpoint path

    def test_payload_with_post_none(self, audio, rf_request):
        # post=None: no episode context, no poster, no blog, no transcript
        payload = build_player_payload(audio, post=None, request=rf_request)
        assert payload["poster"] == ""
        assert payload["transcript"] is None

    def test_inline_url_without_post_has_no_post_id(self, audio, rf_request):
        # A transcript with post=None -> endpoint URL carries no post_id query.
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        payload = build_player_payload(audio, post=None, request=rf_request)
        expected = rf_request.build_absolute_uri(reverse("cast:api:audio_player_transcript", kwargs={"pk": audio.pk}))
        assert payload["transcript"] == {"url": expected}

    def test_inline_transcript_false_returns_cues(self, audio, episode, rf_request):
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        payload = build_player_payload(audio, post=episode, request=rf_request, inline_transcript=False)
        assert payload["transcript"] == {"cues": [{"start": 0.0, "end": 1.0, "speaker": "", "text": "hi"}]}


@pytest.mark.django_db
class TestFallbackEndpoint:
    def _url(self, audio):
        return reverse("cast:api:audio_player_transcript", kwargs={"pk": audio.pk})

    def test_public_read_returns_sanitized_cues(self, client, audio, episode):
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        response = client.get(self._url(audio), {"post_id": episode.pk})
        assert response.status_code == 200
        assert response.json() == {"cues": [{"start": 0.0, "end": 1.0, "speaker": "", "text": "hi"}]}

    def test_public_read_via_body_audio_membership(self, client, audio, post_with_audio):
        # audio belongs to the post via a body audio block (media_lookup branch)
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        response = client.get(self._url(audio), {"post_id": post_with_audio.pk})
        assert response.status_code == 200
        assert response.json() == {"cues": [{"start": 0.0, "end": 1.0, "speaker": "", "text": "hi"}]}

    def test_public_read_preserves_allowed_speaker_and_strips_non_contributor(self, client, audio, episode):
        # End-to-end through AudioPlayerTranscriptView: an allowed (visible
        # contributor) speaker label survives the public speaker mapping +
        # sanitization, while a non-contributor label is stripped to "" — the
        # cue text is preserved either way (only the label is the privacy gate).
        from cast.models import Contributor, EpisodeContributor

        host = Contributor.objects.create(display_name="Live Host", slug="live-host-endpoint")
        EpisodeContributor.objects.create(
            episode=episode,
            contributor=host,
            role=EpisodeContributor.ROLE_HOST,
            sort_order=0,
        )
        episode.save_revision().publish()
        create_transcript(
            audio=audio,
            podlove={
                "transcripts": [
                    {"start_ms": 0, "end_ms": 1000, "speaker": "Live Host", "voice": "Live Host", "text": "kept"},
                    {"start_ms": 1000, "end_ms": 2000, "speaker": "Draft Guest", "voice": "Draft Guest", "text": "x"},
                ]
            },
        )
        response = client.get(self._url(audio), {"post_id": episode.pk})
        assert response.status_code == 200
        cues = response.json()["cues"]
        by_text = {cue["text"]: cue["speaker"] for cue in cues}
        assert by_text == {"kept": "Live Host", "x": ""}

    def test_404_without_post_id(self, client, audio):
        assert client.get(self._url(audio)).status_code == 404

    def test_404_on_mismatched_post(self, client, audio, episode, post):
        # `post` does not own this audio
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        assert client.get(self._url(audio), {"post_id": post.pk}).status_code == 404

    def test_404_on_non_live_post(self, client, audio, episode):
        episode.live = False
        episode.save()
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        assert client.get(self._url(audio), {"post_id": episode.pk}).status_code == 404

    def test_404_on_bad_post_id(self, client, audio):
        assert client.get(self._url(audio), {"post_id": "not-an-int"}).status_code == 404

    def test_never_serves_raw_podlove(self, client, audio, episode):
        create_transcript(
            audio=audio,
            podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "speaker": "Secret", "text": "hi", "ln": 99}]},
        )
        data = client.get(self._url(audio), {"post_id": episode.pk}).json()
        assert set(data.keys()) == {"cues"}
        for cue in data["cues"]:
            assert set(cue.keys()) == {"start", "end", "speaker", "text"}

    def test_sets_cache_control_and_etag(self, client, audio, episode):
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        response = client.get(self._url(audio), {"post_id": episode.pk})
        assert response.status_code == 200
        assert "max-age" in response["Cache-Control"]
        assert "public" in response["Cache-Control"]
        assert response["ETag"]

    def test_304_on_matching_if_none_match(self, client, audio, episode):
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        first = client.get(self._url(audio), {"post_id": episode.pk})
        etag = first["ETag"]
        again = client.get(self._url(audio), {"post_id": episode.pk}, HTTP_IF_NONE_MATCH=etag)
        assert again.status_code == 304
        assert again.content == b""
        assert again["ETag"] == etag


class TestContextFlags:
    def test_podlove_mode(self, settings):
        settings.CAST_AUDIO_PLAYER = "podlove"
        assert audio_player_context_flags(enabled=True) == {
            "use_podlove_player": True,
            "use_custom_audio_player": False,
        }

    def test_custom_mode(self, settings):
        settings.CAST_AUDIO_PLAYER = "custom"
        assert audio_player_context_flags(enabled=True) == {
            "use_podlove_player": False,
            "use_custom_audio_player": True,
        }

    def test_disabled_when_no_audio(self, settings):
        settings.CAST_AUDIO_PLAYER = "custom"
        assert audio_player_context_flags(enabled=False) == {
            "use_podlove_player": False,
            "use_custom_audio_player": False,
        }


class TestSettingsAndChecks:
    def test_defaults_present(self):
        assert appsettings.CAST_AUDIO_PLAYER == "podlove"

    def test_inline_cap_setting_removed(self):
        # The byte cap was removed when the transcript became always-lazy.
        from cast.checks import CAST_SETTING_TYPES

        assert not hasattr(appsettings, "CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES")
        assert all(name != "CAST_PLAYER_INLINE_TRANSCRIPT_MAX_BYTES" for name, _ in CAST_SETTING_TYPES)

    def test_audio_player_value_check_passes_for_valid(self, settings):
        settings.CAST_AUDIO_PLAYER = "custom"
        assert check_cast_audio_player_settings() == []

    def test_audio_player_value_check_passes_when_unset(self):
        assert check_cast_audio_player_settings() == []

    def test_audio_player_value_check_skips_explicit_none(self, settings):
        settings.CAST_AUDIO_PLAYER = None
        assert check_cast_audio_player_settings() == []

    def test_audio_player_value_check_fails_for_invalid(self, settings):
        settings.CAST_AUDIO_PLAYER = "bogus"
        errors = check_cast_audio_player_settings()
        assert [error.id for error in errors] == ["cast.E005"]

    def test_setting_type_check_includes_audio_player(self, settings):
        settings.CAST_AUDIO_PLAYER = 123  # wrong type
        error_ids = [error.id for error in check_cast_setting_types()]
        assert "cast.E001" in error_ids


@pytest.mark.django_db
class TestCustomPlayerTag:
    def _render(self, audio, episode, rf_request, extra=""):
        from django.template import Context, Template

        template = Template("{% load cast_audio_player %}{% cast_custom_player audio episode" + extra + " %}")
        return template.render(Context({"audio": audio, "episode": episode, "request": rf_request}))

    def test_default_renders_in_transport_share(self, audio, episode, rf_request):
        html = self._render(audio, episode, rf_request)
        assert "<cast-audio-player" in html
        assert 'data-share="none"' not in html

    def test_transport_share_false_opts_out(self, audio, episode, rf_request):
        html = self._render(audio, episode, rf_request, extra=" transport_share=False")
        assert 'data-share="none"' in html
