"""Tests for the custom audio player payload builder, settings, checks, and fallback endpoint."""

import logging
from datetime import timedelta

import pytest
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


class TestParseChapterStartSeconds:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("00:01:01", 61),
            ("01:02:03", 3723),
            ("02:05", 125),
            ("00:00:05.789", 5.789),
            (10, 10),
            (10.9, 10.9),
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
        assert response["Cache-Control"] == "public, max-age=30, must-revalidate"
        assert response["ETag"]

    def test_304_on_matching_if_none_match(self, client, audio, episode):
        create_transcript(audio=audio, podlove={"transcripts": [{"start_ms": 0, "end_ms": 1000, "text": "hi"}]})
        first = client.get(self._url(audio), {"post_id": episode.pk})
        etag = first["ETag"]
        again = client.get(self._url(audio), {"post_id": episode.pk}, HTTP_IF_NONE_MATCH=etag)
        assert again.status_code == 304
        assert again.content == b""
        assert again["ETag"] == etag
        assert again["Cache-Control"] == "public, max-age=30, must-revalidate"


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


@pytest.mark.django_db
def test_subsecond_chapters_survive_audio_player_and_chapters_endpoint(client, episode, rf_request):
    from datetime import time

    audio = episode.podcast_audio
    ChapterMark.objects.create(audio=audio, start=time(0, 1, 0, 900000), title="Second")
    ChapterMark.objects.create(audio=audio, start=time(0, 1, 0, 100000), title="First")
    assert [chapter["start"] for chapter in audio.chapters] == ["00:01:00.100", "00:01:00.900"]
    payload = build_player_payload(audio, post=episode, request=rf_request)
    assert payload["chapters"] == [{"start": 60.1, "title": "First"}, {"start": 60.9, "title": "Second"}]
    response = client.get(reverse("cast:chapters-json", kwargs={"pk": audio.pk}), {"episode_id": episode.pk})
    assert response.status_code == 200
    assert [chapter["startTime"] for chapter in response.json()["chapters"]] == [60.1, 60.9]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("start", 10**400),
        ("start_ms", 10**400),
        ("start", "9" * 400 + ":00:00"),
        ("end", 10**400),
        ("end_ms", 10**400),
    ],
)
def test_public_transcript_endpoint_normalizes_oversized_times(client, episode, field, value):
    import json

    from django.core.files.base import ContentFile

    from cast.models import Transcript

    audio = episode.podcast_audio
    transcript = create_transcript(audio=audio)
    segments = [{"start": 0, "end": 1, "text": "extreme", field: value}, {"start": 2, "end": 3, "text": "valid"}]
    # Existing stored JSON need not have passed the current derivation path.
    transcript.podlove.save(
        "synthetic-extreme.json", ContentFile(json.dumps({"transcripts": segments}).encode()), save=False
    )
    Transcript.objects.filter(pk=transcript.pk).update(podlove=transcript.podlove.name)
    response = client.get(
        reverse("cast:api:audio_player_transcript", kwargs={"pk": audio.pk}), {"post_id": episode.pk}
    )
    assert response.status_code == 200
    cues = response.json()["cues"]
    assert any(cue["text"] == "valid" and cue["start"] == 2 for cue in cues)
    assert all(cue["end"] > cue["start"] for cue in cues)


def _cold_card_episode(episode):
    """Return a freshly loaded concrete episode with cold Django and content-type caches."""
    from django.contrib.contenttypes.models import ContentType
    from django.core.cache import caches
    from wagtail.models import Page

    page = Page.objects.filter(pk=episode.pk).specific().get()
    for cache in caches.all():
        cache.clear()
    ContentType.objects.clear_cache()
    return page


def _payload_queries(audio, episode, request, **kwargs):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from cast.models import Audio

    audio = Audio.objects.get(pk=audio.pk)
    card = _cold_card_episode(episode)
    for name, value in kwargs.pop("attrs", {}).items():
        setattr(card, name, value)
    with CaptureQueriesContext(connection) as queries:
        payload = build_player_payload(audio, post=card, request=request, **kwargs)
    return payload, [query["sql"] for query in queries.captured_queries]


@pytest.mark.django_db
def test_cold_card_permalink_adds_no_queries(audio, episode):
    """Regression: resolving the permalink with ``Page.get_url`` added two Site queries per render."""
    from django.test import RequestFactory

    without_permalink, baseline = _payload_queries(audio, episode, RequestFactory().get("/"), permalink="")
    payload, queries = _payload_queries(audio, episode, RequestFactory().get("/"))
    assert "permalink" not in without_permalink
    assert "permalink" not in payload
    assert len(queries) == len(baseline)
    assert not any("wagtailcore_site" in sql for sql in queries)


@pytest.mark.django_db
def test_player_payload_uses_repository_page_url(audio, episode, rf_request):
    _, baseline = _payload_queries(audio, episode, rf_request, permalink="")
    payload, queries = _payload_queries(audio, episode, rf_request, attrs={"page_url": "/podcast/test-podcast-entry/"})
    assert payload["permalink"] == "http://testserver/podcast/test-podcast-entry/"
    assert len(queries) == len(baseline)


@pytest.mark.django_db
def test_player_payload_uses_page_url_of_wrapped_specific_page(audio, episode, rf_request):
    from types import SimpleNamespace

    card = _cold_card_episode(episode)
    card.page_url = "https://example.com/podcast/test-podcast-entry/"
    payload = build_player_payload(audio, post=SimpleNamespace(pk=card.pk, specific=card), request=rf_request)
    assert payload["permalink"] == "https://example.com/podcast/test-podcast-entry/"


@pytest.mark.django_db
def test_player_payload_uses_request_local_page_link_cache(audio, episode, rf_request):
    from cast.wagtail_hooks import PageLinkHandlerWithCache

    _, baseline = _payload_queries(audio, episode, rf_request, permalink="")
    PageLinkHandlerWithCache.cache_url(episode.pk, "/cached/episode/")
    payload, queries = _payload_queries(audio, episode, rf_request)
    assert payload["permalink"] == "http://testserver/cached/episode/"
    assert len(queries) == len(baseline)


@pytest.mark.django_db
def test_player_payload_uses_wagtail_request_site_cache(audio, episode):
    from django.test import RequestFactory

    _, baseline = _payload_queries(audio, episode, RequestFactory().get("/"), permalink="")
    request = RequestFactory().get("/")
    expected = request.build_absolute_uri(episode.get_url(request))
    payload, queries = _payload_queries(audio, episode, request)
    assert payload["permalink"] == expected
    assert len(queries) == len(baseline)


@pytest.mark.django_db
def test_request_site_cache_handles_multiple_sites(audio, episode, django_assert_num_queries):
    from django.test import RequestFactory
    from wagtail.models import Page, Site

    other_root = Page.get_first_root_node().add_child(instance=Page(title="Other", slug="other-root"))
    other_site = Site.objects.create(hostname="other.example", port=443, root_page=other_root)
    request = RequestFactory().get("/")
    episode.get_url(request)  # fills the request-scoped Wagtail caches
    page_site = episode.get_site()
    card = _cold_card_episode(episode)
    card.blog  # noqa: B018 - resolve the parent blog outside the budget
    build_player_payload(audio, post=card, request=request)
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as baseline:
        build_player_payload(audio, post=card, request=request, permalink="")

    request._wagtail_site = other_site
    with django_assert_num_queries(len(baseline.captured_queries)):
        foreign = build_player_payload(audio, post=card, request=request)
    root_url, page_path = episode.get_url_parts(request)[1:]
    assert foreign["permalink"] == f"{root_url}{page_path}"

    request._wagtail_site = page_site
    local = build_player_payload(audio, post=card, request=request)
    assert local["permalink"] == request.build_absolute_uri(page_path)

    del request._wagtail_site
    assert build_player_payload(audio, post=card, request=request)["permalink"] == f"{root_url}{page_path}"


@pytest.mark.django_db
def test_request_site_cache_omits_ambiguous_shared_roots_without_site_query(audio, episode, django_assert_num_queries):
    """A page under two sites' shared root would make Wagtail run ``Site.find_for_request``."""
    from django.test import RequestFactory
    from wagtail.models import Site

    page_site = episode.get_site()
    Site.objects.create(hostname="alias.example", port=443, root_page=page_site.root_page)
    request = RequestFactory().get("/")
    request._wagtail_cached_site_root_paths = Site.get_site_root_paths()
    card = _cold_card_episode(episode)
    card.blog  # noqa: B018 - resolve the parent blog outside the budget
    build_player_payload(audio, post=card, request=request, permalink="")
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as baseline:
        build_player_payload(audio, post=card, request=request, permalink="")
    with django_assert_num_queries(len(baseline.captured_queries)):
        payload = build_player_payload(audio, post=card, request=request)
    assert "permalink" not in payload
    assert not hasattr(request, "_wagtail_site")

    request._wagtail_site = page_site
    assert build_player_payload(audio, post=card, request=request)["permalink"].startswith("http://testserver/")


@pytest.mark.django_db
def test_request_site_cache_skips_unroutable_pages(audio, rf_request):
    from types import SimpleNamespace

    rf_request._wagtail_cached_site_root_paths = []
    for parts in (None, (1, None, None)):
        post = SimpleNamespace(pk="x", get_url_parts=lambda request, parts=parts: parts)
        assert "permalink" not in build_player_payload(audio, post=post, request=rf_request)
    assert "permalink" not in build_player_payload(audio, post=SimpleNamespace(pk="x"), request=rf_request)


@pytest.mark.django_db
def test_explicit_permalink_overrides_resolution(audio, episode, rf_request):
    payload = build_player_payload(audio, post=episode, request=rf_request, permalink="/explicit/")
    assert payload["permalink"] == "http://testserver/explicit/"
    assert "permalink" not in build_player_payload(audio, post=episode, request=rf_request, permalink="javascript:x")
    assert "permalink" not in build_player_payload(audio, post=None, request=rf_request)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [None, 42, "javascript:alert(1)", "data:text/html,test", "mailto:test@example.test", "https://", "https://["],
)
def test_player_payload_omits_unsupported_post_urls(audio, rf_request, url):
    from types import SimpleNamespace

    post = SimpleNamespace(page_url=url)
    assert "permalink" not in build_player_payload(audio, post=post, request=rf_request)
    assert "permalink" not in build_player_payload(audio, post=None, request=rf_request, permalink=url)


@pytest.mark.django_db
def test_rendered_detail_player_uses_request_origin_with_relative_page_context(
    client, post_with_audio, audio, settings
):
    import json
    from urllib.parse import urlsplit

    from bs4 import BeautifulSoup

    settings.CAST_AUDIO_PLAYER = "custom"
    path = urlsplit(post_with_audio.get_url()).path
    response = client.get(path + "?t=12", secure=True, HTTP_HOST="example.com")
    assert response.status_code == 200
    script = BeautifulSoup(response.content, "html.parser").find("script", id=f"cast-player-data-{audio.pk}")
    assert script is not None
    payload = json.loads(script.string)
    assert payload["permalink"] == "https://example.com" + path


@pytest.mark.django_db
def test_relative_permalink_without_request_is_omitted(audio):
    from types import SimpleNamespace

    assert "permalink" not in build_player_payload(audio, post=SimpleNamespace(page_url="/synthetic/"), request=None)
    assert "permalink" not in build_player_payload(audio, post=SimpleNamespace(pk=1), request=None)
